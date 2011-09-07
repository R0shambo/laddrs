import datetime
import logging
import math
import random
import re
import string
import StringIO

from django.template.defaultfilters import slugify

from google.appengine.api import memcache
from google.appengine.api import users
from google.appengine.ext import blobstore
from google.appengine.ext import db

from laddrslib import util

from sc2ranks import Sc2Ranks
from sc2replaylib.replay import Replay

MC_EXP_SHORT=60
MC_EXP_MED=1200
MC_EXP_LONG=86400

MC_PL="public-ladders"
MC_L4U="ladders-for-user"
MC_M4L="matches-for-ladder"
MC_P4L="players-for-ladder"
MC_SC2RP="sc2rank-player"

DEFAULT_ELO_RATING=1600

REGION_RE = re.compile("^(us|eu|kr|tw|sea|ru|la)$")
PUNCTUATION_RE = re.compile("[%s]" % re.escape(string.punctuation))
sc2ranks_api = Sc2Ranks("laddrs.appspot.com")

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


  def add_match(self, user_player, replay_data, filename, force=False):
    if not db.is_in_transaction():
      return db.run_in_transaction(_make_transaction, self.add_match,
          user_player, replay_data, filename, force)
    else:
      replay_file = StringIO.StringIO(replay_data)
      replay = None
      try:
        replay = Replay(replay_file)
      except:
        raise SC2Match.ReplayParseFailed

      # determine the winner and loser players.
      if replay.teams[0].outcome() == 'Won':
        replay_winners = replay.teams[0].players
        replay_losers = replay.teams[1].players
      elif replay.teams[1].outcome() == 'Won':
        replay_winners = replay.teams[1].players
        replay_losers = replay.teams[0].players
      else:
        raise SC2Match.ReplayHasNoWinner

      # now check that players are in the ladder.
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
        pass
      elif (not user_in_replay):
        raise SC2Match.NotReplayOfUploader

      # make sure this replay was not previously uploaded
      existing_match = self.find_match(
          winners[0], losers[0], replay.timestamp())
      if existing_match:
        raise SC2Match.MatchAlreadyExists

      (winner_delta, loser_delta) = SC2Player.adjust_rating(winners, losers)

      for p in winners:
        p.matches_played = p.matches_played + 1
        p.wins = p.wins + 1
        if not p.last_played or p.last_played < replay.timestamp_local():
          p.last_played = replay.timestamp_local()
        p.put()

      for p in losers:
        p.matches_played = p.matches_played + 1
        p.losses = p.losses + 1
        if not p.last_played or p.last_played < replay.timestamp_local():
          p.last_played = replay.timestamp_local()
        p.put()

      self.matches_played = self.matches_played + 1
      self.put()

      filename = slugify(filename[:filename.rfind('.')])
      if filename:
        filename = filename + '.SC2Replay'

      match = SC2Match(
          parent=self,
          key_name=SC2Match.match_key(winners[0], losers[0], replay.timestamp()),
          uploader=user_player,
          replay=db.Blob(replay_data),
          filename=filename,
          winner_keys=[e.key() for e in winners],
          winner_races=winner_races,
          winner_colors=winner_colors,
          winner_delta=winner_delta,
          loser_keys=[e.key() for e in losers],
          loser_races=loser_races,
          loser_colors=loser_colors,
          loser_delta=loser_delta,
          mapname=replay.map_human_friendly(),
          match_date_utc=replay.timestamp(),
          match_date_local=replay.timestamp_local(),
          duration=str(datetime.timedelta(seconds=replay.duration())),
          version='.'.join([str(n) for n in replay.version()]))

      match.put()

      for p in winners + losers:
        memcache.delete(p.user_id, namespace=MC_L4U)
      memcache.delete(self.get_ladder_key(), namespace=MC_P4L)
      memcache.delete(self.get_ladder_key(), namespace=MC_M4L)
      if self.public:
        memcache.delete(MC_PL)
      return match

  def remove_match(self, match):
    if not db.is_in_transaction():
      return db.run_in_transaction(_make_transaction, self.remove_match, match)
    else:
      # make sure there's not funny business going on.
      if match.parent().get_ladder_key() != self.get_ladder_key():
        raise SC2Match.InvalidRemoval(
            "%s != %s" % match.parent().get_ladder_key(), self.get_ladder_key())

      winners = [db.get(k) for k in match.winner_keys]
      for p in winners:
        p.matches_played = p.matches_played - 1
        p.wins = p.wins - 1
        if p.matches_played:
          p.rating = p.rating - match.winner_delta
          if p.rating < 1: p.rating = 1
        else:
          p.rating = 0
        p.put()
      losers = [db.get(k) for k in match.loser_keys]
      for p in losers:
        p.matches_played = p.matches_played - 1
        p.losses = p.losses - 1
        if p.matches_played:
          p.rating = p.rating - match.loser_delta
        else:
          p.rating = 0
        p.put()

      self.matches_played = self.matches_played - 1
      self.put()

      match.delete()

      for p in winners + losers:
        memcache.delete(p.user_id, namespace=MC_L4U)
      memcache.delete(self.get_ladder_key(), namespace=MC_P4L)
      memcache.delete(self.get_ladder_key(), namespace=MC_M4L)
      if self.public:
        memcache.delete(MC_PL)
      return True

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
        logging.info("get ladder for player %s" % player.name)
        ladder = player.get_ladder()
        logging.info("got ladder %s" % ladder.get_ladder_key())
        ladder.user_player = player
        ladder.user_player.rank = SC2Player.gql(
            "WHERE ANCESTOR IS :1 AND rating > :2",
            ladder.key(), player.rating).count() + 1
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

    matches = memcache.get(self.get_ladder_key(), namespace=MC_M4L)
    if not matches:
      logging.info("fetching matches for %s", self.get_ladder_key())
      matches = SC2Match.gql(
          "WHERE ANCESTOR IS :1", self.key())
      memcache.add(
          self.get_ladder_key(), matches, namespace=MC_M4L, time=MC_EXP_MED)

    beefy_matches = []
    for match in matches:
      winner_keys = match.winner_keys
      match.winners = []
      for k in winner_keys:
        i = len(match.winners)
        player = db.get(k)
        player.race = match.winner_races[i]
        player.color = match.winner_colors[i]
        player.portrait = player.get_portrait(45)
        match.winners.append(player)
        if user and player.user_id == user.user_id():
          match.you_won = True

      loser_keys = match.loser_keys
      match.losers = []
      for k in loser_keys:
        i = len(match.losers)
        player = db.get(k)
        player.race = match.loser_races[i]
        player.color = match.loser_colors[i]
        player.portrait = player.get_portrait(45)
        match.losers.append(player)
        if user and player.user_id == user.user_id():
          match.you_lost = True

      beefy_matches.append(match)

    return beefy_matches

  def get_player(self, player_name, bnet_id):
    """Retrieves a SC2Player object from the datastore."""
    return db.get(db.Key.from_path(
        'SC2Ladder', self.get_ladder_key(),
        'SC2Player', SC2Player.player_key(player_name, bnet_id)))

  def get_player_by_key(self, player_key):
    """Retrieves a SC2Player object from the datastore."""
    return db.get(db.Key.from_path(
        'SC2Ladder', self.get_ladder_key(), 'SC2Player', player_key))

  def get_players(self, user=None):

    all_players = memcache.get(self.get_ladder_key(), namespace=MC_P4L)
    if not all_players:
      logging.info("fetching players for %s", self.get_ladder_key())
      all_players = SC2Player.gql(
          "WHERE ANCESTOR IS :1", self.key())
      memcache.add(
          self.get_ladder_key(), all_players, namespace=MC_P4L, time=MC_EXP_MED)

    players = []
    new_players = []
    for player in all_players:
      portrait = player.get_portrait(45)
      if portrait:
        player.portrait = portrait
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

  def find_match(self, winner, loser, timestamp):
    return db.get(db.Key.from_path(
        'SC2Ladder', self.get_ladder_key(),
        'SC2Match', SC2Match.match_key(winner, loser, timestamp)))



class SC2Player(db.Model):
  """Ladder players."""
  name = db.StringProperty(required=True)
  bnet_id = db.StringProperty(required=True)
  code = db.StringProperty(required=True)
  user_id = db.StringProperty(required=True)
  joined = db.DateTimeProperty(auto_now_add=True)
  admin = db.BooleanProperty()
  rating = db.IntegerProperty()
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

  def sc2rank_player_key(self):
    return "%s/%s/%s" % (self.parent().region, self.name, self.bnet_id)

  def get_sc2rank(self):
    if not self.bnet_id:
      return
    if not hasattr(self, '_base_character') or not self._base_character:
      self._base_character = memcache.get(self.sc2rank_player_key(),
                                          namespace=MC_SC2RP)
    if not self._base_character:
      logging.info("fetching sc2rank for %s/%s/%s...",
          self.parent().region, self.name, self.bnet_id)
      self._base_character = sc2ranks_api.fetch_base_character(
          self.parent().region, self.name, self.bnet_id)
      # cache for a long time unless there was an error.
      expiry = MC_EXP_LONG
      if hasattr(self._base_character, 'error'):
        expiry = MC_EXP_MED
      memcache.add(self.sc2rank_player_key(), self._base_character,
                   namespace=MC_SC2RP, time=expiry)
    return self._base_character

  def get_portrait(self, size=75):
    """Returns the data needed to render the starcraft profile image."""
    logging.debug("getting portrait for %s/%s", self.name, self.bnet_id)
    base_character = self.get_sc2rank()
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
      if not p.matches_played:
        p.rating = DEFAULT_ELO_RATING
      winner_rating = winner_rating + p.rating
    loser_rating = 0
    for p in losers:
      if not p.matches_played:
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
      p.rating = p.rating + winner_rating_delta
    for p in losers:
      p.rating = p.rating + loser_rating_delta
      if p.rating < 1: p.rating = 1

    return(winner_rating_delta, loser_rating_delta)

class SC2Match(db.Model):
  """Matches are consist of a replay (stored in BlobStore) plus details
     parsed from the replay."""
  uploader = db.ReferenceProperty(SC2Player, collection_name='uploads')
  replay = db.BlobProperty(required=True)
  filename = db.StringProperty()
  uploaded = db.DateTimeProperty(auto_now_add=True)
  winner_keys = db.ListProperty(db.Key)
  winner_races = db.StringListProperty()
  winner_colors = db.StringListProperty()
  winner_delta = db.IntegerProperty(required=True)
  loser_keys = db.ListProperty(db.Key)
  loser_races = db.StringListProperty()
  loser_colors = db.StringListProperty()
  loser_delta = db.IntegerProperty(required=True)
  mapname = db.StringProperty(required=True)
  match_date_utc = db.DateTimeProperty(required=True)
  match_date_local = db.DateTimeProperty(required=True)
  duration = db.StringProperty(required=True)
  version = db.StringProperty(required=True)

  class InvalidRemoval(Exception):
    pass
  class LoserNotInLadder(Exception):
    pass
  class MatchAlreadyExists(Exception):
    pass
  class NotReplayOfUploader(Exception):
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
  def match_key(cls, winner, loser, timestamp):
    return "%s|%s|%s" % (
        winner.get_player_key(), loser.get_player_key(), str(timestamp))


def _make_transaction(method, *args):
  return method(*args)

def as_iterable(arg):
  try:
    return iter(arg)
  except TypeError:
    return (arg,)
