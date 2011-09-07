import datetime
import logging
import math
import operator
import os
import random
import re
import string
import StringIO
import time
import zipfile

from django.template.defaultfilters import slugify

from google.appengine.api import memcache
from google.appengine.api import urlfetch_errors
from google.appengine.api import users
from google.appengine.ext import blobstore
from google.appengine.ext import db

from laddrslib import util

from third_party import glicko2
from third_party.sc2ranks import Sc2Ranks
from third_party.sc2replaylib.replay import Replay

MC_EXP_SHORT=60
MC_EXP_MED=1200
MC_EXP_LONG=86400

MC_PL="public-ladders_v2"
MC_L4U="ladders-for-user_v2"
MC_M4L="matches-for-ladder_v2"
MC_P4L="players-for-ladder_v2"
MC_SC2RP="sc2rank-player_v2"
MC_MATCHES="matches_v2"
MC_FAQS="faqs_v2"

MAX_UNFROZEN_MATCHES=500

GLICKO_RATING=1500
GLICKO_RD=350
GLICKO_VOL=0.06

GAMETYPE_RE = re.compile("\dv\d")
PUNCTUATION_RE = re.compile("[%s]" % re.escape(string.punctuation))
REGION_RE = re.compile("^(us|eu|kr|tw|sea|ru|la)$")

sc2ranks_api = Sc2Ranks("laddrs.appspot.com")
sc2ranks_throttle = time.time()


class SC2Ladder(db.Model):
  """Ladders ultimately consist of a collection of players and the
     matches/replays between players in the ladder."""
  name = db.StringProperty(required=True)
  region = db.StringProperty(required=True)
  description = db.TextProperty()
  created = db.DateTimeProperty(auto_now_add=True)
  public = db.BooleanProperty()
  invite_only = db.BooleanProperty()
  invite_code = db.IntegerProperty(required=True)
  matches_played = db.IntegerProperty(required=True)
  minimum_rating_period = db.IntegerProperty(default=0)
  players = db.IntegerProperty()

  class AlreadyExists(Exception):
    pass
  class DescriptionMissing(Exception):
    pass
  class InvalidName(Exception):
    pass
  class InvalidRegion(Exception):
    pass
  class NameMissing(Exception):
    pass
  class NotFound(Exception):
    pass
  class PeriodsOutOfOrder(Exception):
    pass


  @classmethod
  def ladder_key(cls, ladder_name):
    return slugify(ladder_name)

  def get_ladder_key(self):
    return self.ladder_key(self.name)

  @classmethod
  def gen_ladder_invite_code(cls):
    return random.getrandbits(17)

  @classmethod
  def create_ladder(cls, user, ladder_name, region, description, public,
      invite_only, player_name, bnet_id, char_code):
    if not db.is_in_transaction():
      return db.run_in_transaction(_make_transaction, cls.create_ladder,
          user, ladder_name, region, description, public, invite_only,
          player_name, bnet_id, char_code)
    else:
      # cleanup
      ladder_name = ladder_name.strip()
      # sanity checks.
      if not ladder_name:
        raise SC2Ladder.NameMissing
      if "<" in ladder_name or ">" in ladder_name or not slugify(ladder_name):
        raise SC2Ladder.InvalidName
      if not description:
        raise SC2Ladder.DescriptionMissing
      if not REGION_RE.match(region):
        raise SC2Ladder.InvalidRegion

      # check if ladder already exists.
      ladder = cls.get_ladder_by_name(ladder_name)
      if ladder:
        raise SC2Ladder.AlreadyExists

      ladder = SC2Ladder(
          key_name=cls.ladder_key(ladder_name),
          name=ladder_name,
          region=region,
          description=description,
          public=public,
          invite_only=invite_only,
          invite_code=cls.gen_ladder_invite_code(),
          matches_played=0,
          players=0)

      ladder.put()

      player = ladder.add_player(
          player_name, bnet_id, char_code, user, admin=True)

      memcache.delete(user.user_id(), namespace=MC_L4U)
      if public:
        memcache.delete(MC_PL)

      return ladder

  def update_ladder(self, description, public, invite_only, regen_invite_code):
    if not db.is_in_transaction():
      return db.run_in_transaction(_make_transaction, self.update_ladder,
          description, public, invite_only, regen_invite_code)
    else:
      # sanity checks.
      if not description:
        raise SC2Ladder.DescriptionMissing

      self.description = description
      self.public = public
      self.invite_only = invite_only
      if regen_invite_code:
        self.invite_code = self.gen_ladder_invite_code()

      self.put()

      memcache.delete(users.get_current_user().user_id(), namespace=MC_L4U)
      memcache.delete(MC_PL)
      return self

  def add_player(self, player_name, bnet_id, char_code, user, admin=False):
    if not db.is_in_transaction():
      return db.run_in_transaction(_make_transaction, self.add_player,
          player_name, bnet_id, char_code, user, admin)
    else:
      # cleanup
      player_name = player_name.strip()
      bnet_id = bnet_id.strip()
      char_code = char_code.strip()
      # sanity checks
      if not player_name:
        raise SC2Player.NameMissing
      if PUNCTUATION_RE.search(player_name) or not slugify(player_name):
        raise SC2Player.InvalidName
      if not char_code:
        raise SC2Player.CharCodeMissing
      if not char_code.isdigit():
        raise SC2Player.InvalidCharCode
      if not bnet_id:
        raise SC2Player.BNetIdMissing
      if not bnet_id.isdigit():
        raise SC2Player.InvalidBNetId

      if self.get_player(player_name, bnet_id):
        raise SC2Player.AlreadyExists

      player = SC2Player(
          parent=self,
          key_name=SC2Player.player_key(player_name, bnet_id),
          name=player_name,
          nickname=player_name,
          bnet_id=bnet_id,
          code=char_code,
          user_id=user.user_id(),
          rating=0,
          matches_played=0,
          wins=0,
          losses=0,
          admin=admin)

      player.put()
      self.players = self.players + 1
      self.put()
      memcache.delete(user.user_id(), namespace=MC_L4U)
      memcache.delete(self.get_ladder_key(), namespace=MC_P4L)
      if self.public:
        memcache.delete(MC_PL)
      return player

  def remove_player(self, player):
    if not db.is_in_transaction():
      return db.run_in_transaction(_make_transaction, self.remove_player,
          player)
    else:
      # refetch player as part of transaction
      player = self.get_player(player.name, player.bnet_id)

      # player may already have been removed
      if not player:
        return True

      # only delete inactive players
      if not player.matches_played and not player.admin:
        player.delete()
        self.players = self.players - 1
        self.put()

        memcache.delete(player.user_id, namespace=MC_L4U)
        memcache.delete(self.get_ladder_key(), namespace=MC_P4L)
        if self.public:
          memcache.delete(MC_PL)
        return True
      # nothing deleted
      return False

  def _reticulate_match_history(self, add_matches=[], remove_match=None):
    # fetch and reset all player ratings to frozen ratings.
    players = {}
    for player in self.get_players(fast=True):
      player.glicko_player = glicko2.Player(name=player.name)
      player.opp_rating_list = []
      player.opp_rd_list = []
      player.outcome_list = []
      if player.frozen_glicko_rating:
        # float() is required so datastore object is not used.
        player.glicko_player.setRating(player.frozen_glicko_rating)
      if player.frozen_glicko_rd:
        player.glicko_player.setRd(player.frozen_glicko_rd)
      if player.frozen_glicko_vol:
        player.glicko_player.vol = player.frozen_glicko_vol
      logging.info("%s loading rating %f/%f/%f", player.name,
          player.glicko_player.rating, player.glicko_player.rd,
          player.glicko_player.vol)
      players[player.key()] = player

    # get all unfrozen matches and replay rating adjustments.
    matches = SC2Match.gql(
        "WHERE ANCESTOR IS :1 AND frozen = FALSE", self.key())
    # GET ALL THE MATCHES!
    match_history = [m for m in matches] + add_matches
    # and sort them by date.
    match_history.sort(key=operator.attrgetter('match_date_utc'))

    # if there are more matches than the allowed number of unfrozen matches,
    # we'll need to freeze the extras.
    matches_to_freeze = len(match_history) - MAX_UNFROZEN_MATCHES
    # okay now iterate through all the matches to replay rating adjustments.
    frozened_matches = []
    curr_rating_period = self.minimum_rating_period or 0
    curr_rating_period_matches = []
    for match in match_history:

      # if this is the match we are removing, skip it.
      if (remove_match and
          remove_match.get_match_key() == match.get_match_key()):
        logging.info("skipping match %s (%s)", match.name,
            match.get_match_key())
        continue

      new_rating_period = match.get_rating_period()

      # set the first current period
      if not curr_rating_period: curr_rating_period = new_rating_period

      # if rating_period has finished, update players.
      if curr_rating_period < new_rating_period:
        newly_frozened_matches = 0
        while (curr_rating_period < new_rating_period):
          logging.info("calculating player ratings for RP%d",
              curr_rating_period)
          self._reticulate_rating_period(players)

          # do we need to freeze any matches?
          if (matches_to_freeze > 0 and curr_rating_period_matches
              and curr_rating_period < SC2Match.get_rating_period_threshold()):
            logging.info("freezing all matches in RP%d", curr_rating_period)
            # freeze all matches belonging to this rating period
            for freezem in curr_rating_period_matches:
              logging.info("freezing match %s", freezem.get_match_key())
              freezem.frozen = True
              frozened_matches.append(freezem)
              newly_frozened_matches = newly_frozened_matches + 1

          # iterate to next rating_period
          curr_rating_period_matches = []
          curr_rating_period = curr_rating_period + 1
          week = curr_rating_period % 100
          if week == 53:
            curr_rating_period = curr_rating_period + 47

          # set frozen ratings for all players to their currently calculated
          # rating if matches were frozened.
          if newly_frozened_matches:
            for player in players.itervalues():
              player.frozen_glicko_rating = player.glicko_player.rating
              player.frozen_glicko_rd = player.glicko_player.rd
              player.frozen_glicko_vol = player.glicko_player.vol
              logging.info("freezing rating for %s %f/%f/%f", player.name,
                  player.frozen_glicko_rating, player.frozen_glicko_rd,
                  player.frozen_glicko_vol)
            self.minimum_rating_period = curr_rating_period
            matches_to_freeze = matches_to_freeze - newly_frozened_matches
            newly_frozened_matches = 0

      # this should never happen.
      elif curr_rating_period > new_rating_period:
        raise SC2Ladder.PeriodsOutOfOrder

      logging.info("RP%d: replaying match %s (%s)", curr_rating_period,
          match.name, match.get_match_key())
      curr_rating_period_matches.append(match)
      # recreate list of winners and losers from historical match. also
      winning_players = [players[k] for k in match.winner_keys]
      losing_players = [players[k] for k in match.loser_keys]

      # determine what rating and rd to use for opponents.
      winner_rating = (sum([p.glicko_player.rating for p in winning_players]) /
          len(losing_players))
      winner_rd = sum([p.glicko_player.rd for p in winning_players])
      loser_rating = (sum([p.glicko_player.rating for p in losing_players]) /
          len(winning_players))
      loser_rd = sum([p.glicko_player.rd for p in losing_players])

      for player in winning_players:
        player.opp_rating_list.append(loser_rating)
        player.opp_rd_list.append(loser_rd)
        player.outcome_list.append(1)
      for player in losing_players:
        player.opp_rating_list.append(winner_rating)
        player.opp_rd_list.append(winner_rd)
        player.outcome_list.append(0)

    # calculate pending ratings for the current rating period.
    logging.info("calculating player ratings for RP%d", curr_rating_period)
    self._reticulate_rating_period(players)

    # all done. return player list so they can be saved.
    return (players, frozened_matches)

  def _reticulate_rating_period(self, players):
    for player in players.itervalues():
      # if player competed, update player based on period activity
      old_rating = player.glicko_player.rating
      old_rd = player.glicko_player.rd
      old_vol = player.glicko_player.vol
      if len(player.opp_rating_list):
        player.glicko_player.update_player(
            player.opp_rating_list, player.opp_rd_list, player.outcome_list)
      # but if the player did nothing in this period. adjust RD
      else:
        player.glicko_player.did_not_compete()
      # save glicko ratings to SC2Player object
      player.glicko_rating = player.glicko_player.rating
      player.glicko_rd = player.glicko_player.rd
      player.glicko_vol = player.glicko_player.vol
      #if (player.glicko_rd != 350 or player.glicko_rating != 1500):
      logging.debug("%s updated %f/%f/%f -> %f/%f/%f", player.name,
          old_rating, old_rd, old_vol,
          player.glicko_rating, player.glicko_rd,
          player.glicko_vol)
      # clear glicko lists.
      player.opp_rating_list = []
      player.opp_rd_list = []
      player.outcome_list = []

  def _add_new_match(self, user_player, upload, force):
    replay = None
    try:
      replay = Replay(upload.file)
    except:
      raise SC2Match.ReplayParseFailed

    logging.debug("frozen RP%d vs upload RP%d", self.minimum_rating_period,
        SC2Match.calc_rating_period(replay.timestamp()))
    if (SC2Match.calc_rating_period(replay.timestamp()) <
        self.minimum_rating_period):
      raise SC2Match.ReplayIsTooOld

    # determine the winner and loser players.
    if replay.teams[0].outcome() == 'Won':
      replay_winners = replay.teams[0].players
      replay_losers = replay.teams[1].players
    elif replay.teams[1].outcome() == 'Won':
      replay_winners = replay.teams[1].players
      replay_losers = replay.teams[0].players
    else:
      raise SC2Match.ReplayHasNoWinner

    game_type = replay.game_teams()
    if not GAMETYPE_RE.match(game_type):
      raise SC2Match.IncorrectType(game_type)

    # make sure this replay was not previously uploaded
    existing_matches = SC2Match.gql(
        "WHERE ANCESTOR IS :1 AND identifier = :2", self.key(),
        replay.identifier)
    if self.get_match(replay.identifier()):
      raise SC2Match.MatchAlreadyExists

    # now check that all players are in the ladder.
    winners = []
    winner_races = []
    winner_colors = []
    user_in_replay = False
    for rp in replay_winners:
      player = self.get_player(rp.handle(), rp.bnet_id())
      if not player:
        raise SC2Match.WinnerNotInLadder(
            "%s/%s" % (rp.handle(), rp.bnet_id()))
      winners.append(player)
      winner_races.append(rp.race())
      winner_colors.append(rp.color_name())
      if user_player.user_id == player.user_id:
        user_in_replay = True

    losers = []
    loser_races = []
    loser_colors = []
    for rp in replay_losers:
      player = self.get_player(rp.handle(), rp.bnet_id())
      if not player:
        raise SC2Match.LoserNotInLadder(
            "%s/%s" % (rp.handle(), rp.bnet_id()))
      losers.append(player)
      loser_races.append(rp.race())
      loser_colors.append(rp.color_name())
      if user_player.user_id == player.user_id:
        user_in_replay = True

    # make sure that uploader is either the winner or loser.
    if (force and user_player.admin):
      # allow upload if admin user and force upload checked.
      logging.info("upload to %s forced by admin %s", self.get_ladder_key(),
          user_player.get_player_key())
    elif (not user_in_replay):
      raise SC2Match.NotReplayOfUploader

    # make the replay filename safe!
    filename = slugify(upload.filename[:upload.filename.rfind('.')])
    if filename:
      filename = filename + '.SC2Replay'

    name = ' '.join([str(replay.timestamp()),
        ', '.join([p.name for p in winners]), 'vs',
        ', '.join([p.name for p in losers]), 'on',
        replay.map_human_friendly()])

    return SC2Match(
        parent=self,
        key_name=replay.identifier(),
        name=name,
        uploader=user_player,
        replay=db.Blob(upload.value),
        filename=filename,
        winner_keys=[p.key() for p in winners],
        winner_races=winner_races,
        winner_colors=winner_colors,
        loser_keys=[p.key() for p in losers],
        loser_races=loser_races,
        loser_colors=loser_colors,
        mapname=replay.map_human_friendly(),
        match_date_utc=replay.timestamp(),
        match_date_local=replay.timestamp_local(),
        duration=str(datetime.timedelta(seconds=replay.duration())),
        version='.'.join([str(n) for n in replay.version()]))

  def add_matches(self, user_player, replays, force=False):
    if not db.is_in_transaction():
      (accepted, rejected, players, frozened_matches) = db.run_in_transaction(
          _make_transaction, self.add_matches, user_player, replays, force)
      memcache.delete_multi(
          [m.key().name() for m in frozened_matches], namespace=MC_MATCHES)
      memcache.delete_multi([p.user_id for p in players], namespace=MC_L4U)
      memcache.delete(self.get_ladder_key(), namespace=MC_P4L)
      memcache.delete(self.get_ladder_key(), namespace=MC_M4L)
      if self.public:
        memcache.delete(MC_PL)
      return (accepted, rejected)

    else:
      new_matches = []
      new_matches_idx = {}
      accepted = []
      rejected = []

      for upload in replays:
        try:
          new_match = self._add_new_match(user_player, upload, force)
          if new_match.key() in new_matches_idx:
            raise SC2Match.MatchAlreadyExists
          new_matches.append(new_match)
          new_matches_idx[new_match.key()] = new_match
          accepted.append(upload.filename)
        except SC2Match.IncorrectType, e:
          rejected.append(
              "%s: %s game type is not supported." % (upload.filename, e.args))
        except SC2Match.LoserNotInLadder, e:
          rejected.append(
              "%s: Loser (%s) is not a member of the ladder." % (upload.filename, e.args))
        except SC2Match.MatchAlreadyExists:
          rejected.append(
              "%s: This match has already been uploaded." % upload.filename)
        except SC2Match.NotReplayOfUploader:
          rejected.append(
              "%s: You may only upload your own replays." % upload.filename)
        except SC2Match.ReplayIsTooOld:
          rejected.append(
              "%s: Uploaded replay is too old. Stop living in the past." % upload.filename)
        except SC2Match.ReplayHasNoWinner:
          rejected.append(
              "%s: Replay has no winner." % upload.filename)
        except SC2Match.ReplayParseFailed:
          rejected.append(
              "%s: Unable to parse uploaded replay file." % upload.filename)
        except SC2Match.TooManyPlayers, e:
          rejected.append(
              "%s: Only 1v1 replays allowed. Uploaded replay has %d players." % (upload.filename, e.args))
        except SC2Match.WinnerNotInLadder, e:
          rejected.append(
              "%s: Winner (%s) is not a member of the ladder." % (upload.filename, e.args))

      # check if any replays were actually upload successfully and early out
      # if there were none accepted.
      if len(accepted) == 0:
        return (accepted, rejected, [], [])

      # Now we do the meaty work of pulling down match history so we can insert
      # the match into the proper place in time and accurately adjust player
      # ratings.
      (players, frozened_matches) = self._reticulate_match_history(
          add_matches=new_matches)

      for match in new_matches:
        for key in match.winner_keys:
          player = players[key]
          player.matches_played = player.matches_played + 1
          player.wins = player.wins + 1
        if not player.last_played or player.last_played < match.match_date_utc:
          player.last_played = match.match_date_utc
        for key in match.loser_keys:
          player = players[key]
          player.matches_played = player.matches_played + 1
          player.losses = player.losses + 1
        if not player.last_played or player.last_played < match.match_date_utc:
          player.last_played = match.match_date_utc

      # calculate "fuzzy" rating and zero rating for players with no matches
      players = [p for p in players.itervalues()]
      for player in players:
        if player.matches_played:
          player.fuzzy_rating = player.glicko_rating - player.glicko_rd * 2
          logging.info("save rating for %s %f %f = %f", player.name,
              player.glicko_rating, player.glicko_rd, player.fuzzy_rating)
        else:
          player.fuzzy_rating = 0.0
          player.glicko_rating = 0.0
          player.glicko_rd = 0.0
          player.glicko_vol = 0.0

      # SAVE ALL THE THINGS!
      self.matches_played = self.matches_played + len(new_matches)
      db.put([self] + frozened_matches + new_matches + players)

      return (accepted, rejected, players, frozened_matches)

  def remove_match(self, match):
    if not db.is_in_transaction():
      players = db.run_in_transaction(_make_transaction,
          self.remove_match, match)
      memcache.delete_multi([p.user_id for p in players], namespace=MC_L4U)
      memcache.delete(match.key().name(), namespace=MC_MATCHES)
      memcache.delete(self.get_ladder_key(), namespace=MC_P4L)
      memcache.delete(self.get_ladder_key(), namespace=MC_M4L)
      if self.public:
        memcache.delete(MC_PL)
    else:
      # refetch match as part of transaction
      match = SC2Match.get(match.key())

      # match may already have been removed
      if not match: return []

      if match.frozen:
        raise SC2Match.MatchFrozen()
      # make sure there's not funny business going on.
      if match.parent().get_ladder_key() != self.get_ladder_key():
        raise SC2Match.InvalidRemoval(
            "%s != %s" % match.parent().get_ladder_key(), self.get_ladder_key())

      # recreate rating history without this match.
      (players, _) = self._reticulate_match_history(remove_match=match)

      # update vitals for match participants.
      winners = [players[k] for k in match.winner_keys]
      for p in winners:
        p.matches_played = p.matches_played - 1
        p.wins = p.wins - 1
      losers = [players[k] for k in match.loser_keys]
      for p in losers:
        p.matches_played = p.matches_played - 1
        p.losses = p.losses - 1

      # SAVE ALL THE THINGS!
      self.matches_played = self.matches_played - 1
      players = [p for p in players.itervalues()]
      db.put([self] + players)

      match.delete()
      return players

  def remove_all_the_matches(self):
    if not db.is_in_transaction():
      (match_keys, players) = db.run_in_transaction(_make_transaction,
          self.remove_all_the_matches)
      memcache.delete_multi(
          [k.name() for k in match_keys], namespace=MC_MATCHES)
      memcache.delete_multi([p.user_id for p in players], namespace=MC_L4U)
      memcache.delete(self.get_ladder_key(), namespace=MC_P4L)
      memcache.delete(self.get_ladder_key(), namespace=MC_M4L)
      if self.public:
        memcache.delete(MC_PL)
    else:
      # get all the matches, then delete them.s
      match_keys = [k for k in SC2Match.all(keys_only=True).ancestor(self)]
      db.delete_async(match_keys)
      # get all the players and zero their ratings.
      players = [p for p in self.get_players(fast=True)]
      for player in players:
        player.fuzzy_rating = 0.0
        player.glicko_rating = 0.0
        player.glicko_rd = 0.0
        player.glicko_vol = 0.0
        player.frozen_glicko_rating = 0.0
        player.frozen_glicko_rd = 0.0
        player.frozen_glicko_vol = 0.0
        player.wins = 0
        player.losses = 0
        player.matches_played = 0

      self.matches_played = 0
      self.minimum_rating_period = 0

      # SAVE ALL THE THINGS!
      db.put([self] + players)
      return (match_keys, players)


  @classmethod
  def get_ladder(cls, ladder_key):
    """Retrieves a SC2Ladder object from the datastore."""
    return db.get(ladder_key)

  @classmethod
  def get_ladder_by_name(cls, ladder_name):
    """Retrieves a SC2Ladder object from the datastore."""
    return cls.get_ladder(db.Key.from_path(
        'SC2Ladder', cls.ladder_key(ladder_name)))

  @classmethod
  def get_ladders_for_user(cls, user, retry=True):
    """Queries for SC2Players belonging to User."""
    if not user:
      return []
    # try memcache first
    ladders = memcache.get(user.user_id(), namespace=MC_L4U)
    # fallback to datastore if necessary
    if not ladders:
      ladders = []
      logging.info("fetching players for %s", user.nickname())
      players = SC2Player.gql("WHERE user_id = :1", user.user_id())
      for player in players:
        #logging.info("get ladder for player %s" % player.name)
        ladder = player.get_ladder()
        #logging.info("got ladder %s" % ladder.get_ladder_key())
        ladder.user_player = player
        ladder.user_player.rank = SC2Player.gql(
            "WHERE ANCESTOR IS :1 AND glicko_rating > :2",
            ladder.key(), player.glicko_rating).count() + 1
        ladders.append(ladder)
      # try adding to memcache
      if (not memcache.add(
              user.user_id(), ladders, namespace=MC_L4U, time=MC_EXP_MED)
          and retry):
        # if we were unable to add to memcache, it's possible another process
        # did and it had more up-to-date information (new player added for
        # instance). So let's try again using that.
        ladders = cls.get_ladders_for_user(user, retry=False)
    return ladders

  def get_matches(self, user=None):

    match_keys = memcache.get(self.get_ladder_key(), namespace=MC_M4L)
    if not match_keys:
      logging.info("fetching match keys for %s", self.get_ladder_key())
      query = SC2Match.all(keys_only=True).ancestor(self)
      query.order('-match_date_utc')
      match_keys = [k for k in query]
      memcache.add(
          self.get_ladder_key(), match_keys, namespace=MC_M4L, time=MC_EXP_MED)
    #logging.info("%s match keys: %s", self.get_ladder_key(), str(match_keys))
    matches = memcache.get_multi([k.name() for k in match_keys],
        namespace=MC_MATCHES)
    #logging.info("memcached matches: %s", str(matches))
    fetch_keys = []
    for key in match_keys:
      if not key.name() in matches:
        fetch_keys.append(key)
    # fetch any matches not found in memcache.
    if fetch_keys:
      logging.info("fetching %d matches for %s", len(fetch_keys),
          self.get_ladder_key())
      fetched_matches = SC2Match.get(fetch_keys)
      #logging.info("fetched matches: %s", str(fetched_matches))
      recache = {}
      for (key, match) in zip(fetch_keys, fetched_matches):
        #logging.info("fetched %s for %s", str(match), str(key))
        # this line is literally to force the datastore to fetch the uploading
        # player object so it can be cached along with everything else.
        match.uploader = match.uploader
        # start query for losers asynchronously
        loser_query = db.get_async(match.loser_keys)
        # then block on winners so we can iterate through them.
        match.winners = db.get(match.winner_keys)
        for (player, race, color) in zip(match.winners,
            match.winner_races, match.winner_colors):
          player.race = race
          player.color = color
          player.portrait = player.get_portrait(self.region)
        # block on losers and iterate.
        match.losers = loser_query.get_result()
        for (player, race, color) in zip(match.losers,
            match.loser_races, match.loser_colors):
          player.race = race
          player.color = color
          player.portrait = player.get_portrait(self.region)
        matches[key.name()] = match
        recache[key.name()] = match
      memcache.add_multi(recache, namespace=MC_MATCHES)

    ordered_matches = []
    # flag matches owned by the current user.
    for key in match_keys:
      match = matches[key.name()]
      for player in match.winners:
        if user and player.user_id == user.user_id():
          match.you_won = True
      for player in match.losers:
        if user and player.user_id == user.user_id():
          match.you_lost = True
      ordered_matches.append(match)
    return ordered_matches

  def get_matches_zipfile(self):

    matches = self.get_matches()

    zipio = StringIO.StringIO()

    zip = zipfile.ZipFile(zipio, mode="w", compression=zipfile.ZIP_DEFLATED)
    for match in matches:
      logging.info("compressing %s.SC2Replay", match.name)
      dt = match.match_date_local
      info = zipfile.ZipInfo(filename="%s.SC2Replay" % slugify(match.name),
          date_time=(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second))
      zip.writestr(info, match.replay)
    zip.close()

    zipdata = zipio.getvalue()
    zipio.close()
    return zipdata


  def get_player(self, player_name, bnet_id):
    """Retrieves a SC2Player object from the datastore."""
    return db.get(db.Key.from_path(
        'SC2Ladder', self.get_ladder_key(),
        'SC2Player', SC2Player.player_key(player_name, bnet_id)))

  def get_player_by_key(self, player_key):
    """Retrieves a SC2Player object from the datastore."""
    return db.get(db.Key.from_path(
        'SC2Ladder', self.get_ladder_key(), 'SC2Player', player_key))

  def get_players(self, user=None, fast=False):
    all_players = memcache.get(self.get_ladder_key(), namespace=MC_P4L)
    if not all_players:
      logging.info("fetching players for %s", self.get_ladder_key())
      query = SC2Player.gql(
          "WHERE ANCESTOR IS :1", self.key())
      all_players = []
      for player in query:
        portrait = player.get_portrait(self.region)
        if portrait:
          player.portrait = portrait
        all_players.append(player)
      memcache.add(
          self.get_ladder_key(), all_players, namespace=MC_P4L, time=MC_EXP_MED)
    if fast:
      return all_players

    players = []
    new_players = []
    for player in all_players:
      if player.matches_played > 0:
        players.append(player)
      else:
        new_players.append(player)

    # Determine if user is a member of the ladder.
    user_player = None
    if user:
      for player in players:
        if player.user_id == user.user_id():
          player.this_is_you = True
          user_player = player
      for player in new_players:
        if player.user_id == user.user_id():
          player.this_is_you = True
          user_player = player

    return (players, new_players, user_player)

  def get_user_player(self, user):
    return SC2Player.gql("WHERE ANCESTOR IS :1 AND user_id = :2",
        self.key(), user.user_id()).get()

  @classmethod
  def get_public_ladders(cls):
    """Queries for all public Ladders."""
    # try memcache first
    ladders = memcache.get(MC_PL)
    # fallback to datastore if necessary
    if not ladders:
      logging.info("fetching public ladders")
      q = cls.gql(
          "WHERE public = True ORDER BY matches_played DESC, players DESC")
      ladders = q.fetch(100)
      # try adding to memcache, use short expiration as this may change frequently
      memcache.add(MC_PL, ladders, time=MC_EXP_MED)
    return ladders

  def get_match(self, id):
    return db.get(db.Key.from_path(
        'SC2Ladder', self.get_ladder_key(),
        'SC2Match', id))


class SC2Player(db.Model):
  """Ladder players."""
  name = db.StringProperty(required=True)
  bnet_id = db.StringProperty(required=True)
  code = db.StringProperty(required=True)
  user_id = db.StringProperty(required=True)
  joined = db.DateTimeProperty(auto_now_add=True)
  nickname = db.StringProperty()
  email = db.StringProperty()
  admin = db.BooleanProperty()
  fuzzy_rating = db.FloatProperty()
  glicko_rating = db.FloatProperty()
  glicko_rd = db.FloatProperty()
  glicko_vol = db.FloatProperty()
  frozen_glicko_rating = db.FloatProperty()
  frozen_glicko_rd = db.FloatProperty()
  frozen_glicko_vol = db.FloatProperty()
  matches_played = db.IntegerProperty(required=True)
  wins = db.IntegerProperty(required=True)
  losses = db.IntegerProperty(required=True)
  last_played = db.DateTimeProperty()

  class AlreadyExists(Exception):
    pass
  class BNetIdMissing(Exception):
    pass
  class CharCodeMissing(Exception):
    pass
  class InvalidBNetId(Exception):
    pass
  class InvalidCharCode(Exception):
    pass
  class InvalidName(Exception):
    pass
  class NameMissing(Exception):
    pass

  @classmethod
  def player_key(cls, player_name, bnet_id):
    return "%s/%s" % (slugify(player_name), bnet_id)

  def get_player_key(self):
    return self.player_key(self.name, self.bnet_id)

  def get_ladder(self):
    return self.parent()

  def set_admin(self, admin):
    if not db.is_in_transaction():
      return db.run_in_transaction(_make_transaction, self.set_admin, admin)
    else:
      self.admin = admin
      self.put()
      memcache.delete(self.get_ladder().get_ladder_key(), namespace=MC_P4L)
      return True

  def set_player_info(self, nickname, email):
    if not db.is_in_transaction():
      return db.run_in_transaction(_make_transaction,
        self.set_player_info, nickname, email)
    else:
      self.nickname = nickname
      self.email = email
      self.put()
      memcache.delete(self.get_ladder().get_ladder_key(), namespace=MC_P4L)
      return True


  def sc2rank_player_key(self, region):
    return "%s/%s/%s" % (region, self.name, self.bnet_id)

  def get_sc2rank(self, region):
    global sc2ranks_throttle
    if not self.bnet_id:
      return
    if not hasattr(self, '_base_character') or not self._base_character:
      self._base_character = memcache.get(self.sc2rank_player_key(region),
                                          namespace=MC_SC2RP)
    if not self._base_character:
      if sc2ranks_throttle < time.time():
        logging.info("fetching sc2rank for %s/%s/%s...",
            region, self.name, self.bnet_id)
        try:
          self._base_character = sc2ranks_api.fetch_base_character(
              region, self.name, self.bnet_id)
        except urlfetch_errors.DeadlineExceededError:
          logging.exception("Timed out contacting sc2rank.")
          sc2ranks_throttle = time.time() + 3600
        # cache for a long time unless there was an error.
        expiry = MC_EXP_LONG
        if hasattr(self._base_character, 'error'):
          expiry = MC_EXP_MED
        memcache.add(self.sc2rank_player_key(region), self._base_character,
                     namespace=MC_SC2RP, time=expiry)
      else:
        logging.info("sc2rank api request throttled")
    return self._base_character

  def get_portrait(self, region, size=45):
    """Returns the data needed to render the starcraft profile image."""
    #logging.debug("getting portrait for %s/%s", self.name, self.bnet_id)
    base_character = self.get_sc2rank(region)
    if base_character:
      try:
        portrait = base_character.portrait
        x = -(portrait.column * size)
        y = -(portrait.row * size)
        image = 'portraits-%d-%d.jpg' % (portrait.icon_id, size)
        position = '%dpx %dpx no-repeat; width: %dpx; height: %dpx;' % (x, y, size, size)
        return  {'image': image, 'position': position}
      except:
        logging.warning("failed to get portrait for %s/%s",
            self.name, self.bnet_id, exc_info=True)

  @classmethod
  def adjust_rating(cls, winners, losers):

    winner_rating = 0
    for p in winners:
      if not p.rating:
        p.rating = DEFAULT_ELO_RATING
      winner_rating = winner_rating + p.rating
    loser_rating = 0
    for p in losers:
      if not p.rating:
        p.rating = DEFAULT_ELO_RATING
      loser_rating = loser_rating + p.rating

    rating_diff = winner_rating - loser_rating
    exp = (rating_diff * -1) / 400
    odds = 1 / (1 + math.pow(10, exp))
    bonus = len(losers) - len(winners) + 1
    if bonus < 1: bonus = 1
    if winner_rating < 2100:
        k = 32 * bonus
    elif winner_rating >= 2100 and winner_rating < 2400:
        k = 24 * bonus
    else:
        k = 16 * bonus
    new_winner_rating = round(winner_rating + (k * (1 - odds)))
    winner_rating_delta = new_winner_rating - winner_rating
    new_loser_rating = loser_rating - winner_rating_delta
    loser_rating_delta = new_loser_rating - loser_rating

    winner_rating_delta = int(round(winner_rating_delta / len(winners))) or 1
    loser_rating_delta = int(round(loser_rating_delta / len(losers))) or -1

    for p in winners:
      old_rating = p.rating
      p.rating = p.rating + winner_rating_delta
      logging.info("winning player %s rating %d -> %d",
          p.name, old_rating, p.rating)
    for p in losers:
      old_rating = p.rating
      p.rating = p.rating + loser_rating_delta
      if p.rating < 1: p.rating = 1
      logging.info("losing player %s rating %d -> %d",
          p.name, old_rating, p.rating)


class SC2Match(db.Model):
  """Matches are consist of a replay (stored in BlobStore) plus details
     parsed from the replay."""
  name = db.StringProperty()
  uploader = db.ReferenceProperty(SC2Player, collection_name='uploads')
  replay = db.BlobProperty(required=True)
  filename = db.StringProperty()
  uploaded = db.DateTimeProperty(auto_now_add=True)
  winner_keys = db.ListProperty(db.Key)
  winner_races = db.StringListProperty()
  winner_colors = db.StringListProperty()
  loser_keys = db.ListProperty(db.Key)
  loser_races = db.StringListProperty()
  loser_colors = db.StringListProperty()
  frozen = db.BooleanProperty(default=False)
  mapname = db.StringProperty(required=True)
  match_date_utc = db.DateTimeProperty(required=True)
  match_date_local = db.DateTimeProperty(required=True)
  duration = db.StringProperty(required=True)
  version = db.StringProperty(required=True)

  class IncorrectType(Exception):
    pass
  class InvalidRemoval(Exception):
    pass
  class LoserNotInLadder(Exception):
    pass
  class MatchAlreadyExists(Exception):
    pass
  class MatchFrozen(Exception):
    pass
  class NotReplayOfUploader(Exception):
    pass
  class ReplayIsTooOld(Exception):
    pass
  class ReplayHasNoWinner(Exception):
    pass
  class ReplayParseFailed(Exception):
    pass
  class TooManyPlayers(Exception):
    pass
  class WinnerNotInLadder(Exception):
    pass

  @classmethod
  def calc_rating_period(cls, dt):
    week = int(dt.strftime("%W"))
    year = dt.year
    if week == 53:
      year = year + 1
      week == 0
    return year * 100 + week

  def get_match_key(self):
    return self.key().id_or_name()

  def get_rating_period(self):
    return self.calc_rating_period(self.match_date_utc)

  @classmethod
  def get_rating_period_threshold(cls):
    return cls.calc_rating_period(
        datetime.datetime.utcnow() - datetime.timedelta(days=8))


class FaqEntry(db.Model):
  question = db.StringProperty(required=True)
  answer = db.TextProperty(required=True)
  popularity = db.IntegerProperty(default=0)
  rank = db.IntegerProperty(default=0)

  @classmethod
  def get_faqs(cls):
    faqs = memcache.get(MC_FAQS)
    if not faqs:
      faqs = [f for f in cls.all().order("rank")]
      memcache.set(MC_FAQS, faqs)
    return faqs

  @classmethod
  def update_faq(cls, key, question, answer, rank):
    faq = cls.get(key)
    if faq:
      faq.question = question
      faq.answer = answer
      faq.rank = int(rank)
      faq.put()
      memcache.delete(MC_FAQS)
      return True

  @classmethod
  def new_faq(cls, question, answer, rank):
    faq = cls(question=question, answer=answer, rank=int(rank))
    faq.put()
    memcache.delete(MC_FAQS)
    return faq

def _make_transaction(method, *args):
  return method(*args)
