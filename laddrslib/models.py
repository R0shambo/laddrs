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

    ladder_name = ladder_name.strip()

    if db.is_in_transaction():
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

      return ladder

    # if we got this far, it means we are not inside a transaction, start one.
    rv = db.run_in_transaction(_create_ladder_transaction,
        user, ladder_name, region, description, public, invite_only,
        player_name, bnet_id, char_code)
    memcache.delete(user.user_id(), namespace=MC_L4U)
    if public:
      memcache.delete(MC_PL)
    return rv

  def update_ladder(self, description, public, invite_only, regen_invite_code):
    if db.is_in_transaction():
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

    # if we got this far, it means we are not inside a transaction, start one.
    return db.run_in_transaction(_update_ladder_transaction,
        self, description, public, invite_only, regen_invite_code)

  def add_player(self, player_name, bnet_id, char_code, user, admin=False):
    player_name = player_name.strip()
    bnet_id = bnet_id.strip()
    char_code = char_code.strip()
    if db.is_in_transaction():
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
          rank=DEFAULT_ELO_RATING,
          matches_played=0,
          wins=0,
          losses=0,
          admin=admin)

      player.put()
      self.players = self.players + 1
      self.put()
      return player

    # if we got this far, it means we are not inside a transaction, start one.
    rv = db.run_in_transaction(_add_player_transaction,
        self, player_name, bnet_id, char_code, user, admin)
    memcache.delete(user.user_id(), namespace=MC_L4U)
    memcache.delete(self.get_ladder_key(), namespace=MC_P4L)
    if self.public:
      memcache.delete(MC_PL)
    return rv

  def remove_player(self, player, force=False):
    if db.is_in_transaction():
      # refetch player as part of transaction
      player = self.get_player(player.name, player.bnet_id)

      # player may already have been removed
      if not player:
        return True

      # only delete inactive players
      if force or (not player.matches_played and not player.admin):
        player.delete()
        self.players = self.players - 1
        self.put()
        return True
      
      # nothing deleted
      return False

    # if we got this far, it means we are not inside a transaction, start one.
    rv = db.run_in_transaction(_remove_player_transaction,
        self, player, force)
    memcache.delete(player.user_id, namespace=MC_L4U)
    memcache.delete(self.get_ladder_key(), namespace=MC_P4L)
    if self.public:
      memcache.delete(MC_PL)
    return rv

  def add_match(self, user_player, replay_data, filename):
    if db.is_in_transaction():
      replay_file = StringIO.StringIO(replay_data)
      replay = None
      try:
        replay = Replay(replay_file)
      except:
        raise SC2Match.ReplayParseFailed

      # replays must be 1v1 since this is a 1v1 ladder site afterall.
      number_of_players = (len(replay.teams[0].players) +
          len(replay.teams[1].players))
      if number_of_players != 2:
        raise SC2Match.TooManyPlayers(number_of_players)

      # determine the winner and loser players.
      if replay.teams[0].players[0].outcome() == 'Won':
        replay_winner = replay.teams[0].players[0]
        replay_loser = replay.teams[1].players[0]
      elif replay.teams[1].players[0].outcome() == 'Won':
        replay_winner = replay.teams[1].players[0]
        replay_loser = replay.teams[0].players[0]
      else:
        raise SC2Match.ReplayHasNoWinner

      # now check that players are in the ladder.
      winner = self.get_player(replay_winner.handle(), replay_winner.bnet_id())
      if not winner:
        raise SC2Match.WinnerNotInLadder(
            "%s/%s" % (replay_winner.handle(), replay_winner.bnet_id()))
      loser = self.get_player(replay_loser.handle(), replay_loser.bnet_id())
      if not loser:
        raise SC2Match.LoserNotInLadder(
            "%s/%s" % (replay_loser.handle(), replay_loser.bnet_id()))

      # make sure that uploader is either the winner or loser.
      if (user_player.user_id != winner.user_id
          and user_player.user_id != loser.user_id):
        raise SC2Match.NotReplayOfUploader

      # make sure this replay was not previously uploaded
      existing_match = self.find_match(winner, loser, replay.timestamp())
      if existing_match:
        raise SC2Match.MatchAlreadyExists

      winner.matches_played = winner.matches_played + 1
      winner.wins = winner.wins + 1
      if not winner.last_played or winner.last_played < replay.timestamp_local():
        winner.last_played = replay.timestamp_local()

      loser.matches_played = loser.matches_played + 1
      loser.losses = loser.losses + 1
      if not loser.last_played or loser.last_played < replay.timestamp_local():
        loser.last_played = replay.timestamp_local()

      SC2Player.adjust_ranking(winner, loser)

      winner.put()
      loser.put()

      self.matches_played = self.matches_played + 1
      self.put()

      filename = slugify(filename[:filename.rfind('.')])
      if filename:
        filename = filename + '.SC2Replay'

      match = SC2Match(
          parent=self,
          key_name=SC2Match.match_key(winner, loser, replay.timestamp()),
          uploader=user_player,
          replay=db.Blob(replay_data),
          filename=filename,
          winner=winner,
          winner_race=replay_winner.race(),
          winner_color=replay_winner.color_name(),
          loser=loser,
          loser_race=replay_loser.race(),
          loser_color=replay_loser.color_name(),
          mapname=replay.map_human_friendly(),
          match_date_utc=replay.timestamp(),
          match_date_local=replay.timestamp_local(),
          duration=str(datetime.timedelta(seconds=replay.duration())),
          version='.'.join([str(n) for n in replay.version()]))

      match.put()
      
      memcache.delete(winner.user_id, namespace=MC_L4U)
      memcache.delete(loser.user_id, namespace=MC_L4U)
      memcache.delete(self.get_ladder_key(), namespace=MC_P4L)
      memcache.delete(self.get_ladder_key(), namespace=MC_M4L)
      if self.public:
        memcache.delete(MC_PL)

      return match

    # if we got this far, it means we are not inside a transaction, start one.
    rv = db.run_in_transaction(_add_match_transaction,
        self, user_player, replay_data, filename)
    return rv

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
        ladder.user_player.ranking = SC2Player.gql(
            "WHERE ANCESTOR IS :1 AND rank > :2",
            ladder.key(), player.rank).count() + 1
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
      match.winner.portrait = match.winner.get_portrait(45)
      match.winner.race = match.winner_race
      match.winner.color = match.winner_color
      match.loser.portrait = match.loser.get_portrait(45)
      match.loser.race = match.loser_race
      match.loser.color = match.loser_color
      if user:
        if match.winner.user_id == user.user_id():
          match.you_won = True
        elif match.loser.user_id == user.user_id():
          match.you_lost = True
      beefy_matches.append(match)

    return beefy_matches

  def get_player(self, player_name, bnet_id):
    """Retrieves a SC2Ladder object from the datastore."""
    return db.get(db.Key.from_path(
        'SC2Ladder', self.get_ladder_key(),
        'SC2Player', SC2Player.player_key(player_name, bnet_id)))

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
  rank = db.IntegerProperty(required=True)
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
  def adjust_ranking(cls, winner, loser):
    rank_diff = winner.rank - loser.rank
    exp = (rank_diff * -1) / 400
    odds = 1 / (1 + math.pow(10, exp))
    if winner.rank < 2100:
        k = 32
    elif winner.rank >= 2100 and winner.rank < 2400:
        k = 24
    else:
        k = 16
    new_winner_rank = round(winner.rank + (k * (1 - odds)))
    new_rank_diff = new_winner_rank - winner.rank
    new_loser_rank = loser.rank - new_rank_diff
    if new_loser_rank < 1:
      new_loser_rank = 1

    winner.rank = int(new_winner_rank)
    loser.rank = int(new_loser_rank)

class SC2Match(db.Model):
  """Matches are consist of a replay (stored in BlobStore) plus details
     parsed from the replay."""
  uploader = db.ReferenceProperty(SC2Player, collection_name='uploads')
  replay = db.BlobProperty(required=True)
  filename = db.StringProperty()
  uploaded = db.DateTimeProperty(auto_now_add=True)
  winner = db.ReferenceProperty(SC2Player, collection_name='w_matches')
  winner_race = db.StringProperty(required=True)
  winner_color = db.StringProperty(required=True)
  loser = db.ReferenceProperty(SC2Player, collection_name='l_matches')
  loser_race = db.StringProperty(required=True)
  loser_color = db.StringProperty(required=True)
  mapname = db.StringProperty(required=True)
  match_date_utc = db.DateTimeProperty(required=True)
  match_date_local = db.DateTimeProperty(required=True)
  duration = db.StringProperty(required=True)
  version = db.StringProperty(required=True)

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


def _create_ladder_transaction(user, ladder_name, region, description, public,
    invite_only, player_name, bnet_id, char_code):
  return SC2Ladder.create_ladder(user, ladder_name, region, description, public,
      invite_only, player_name, bnet_id, char_code)

def _update_ladder_transaction(ladder, description, public, invite_only,
    regen_invite_code):
  return ladder.update_ladder(description, public, invite_only,
    regen_invite_code)

def _add_player_transaction(ladder, player_name, bnet_id, char_code, user,
    admin):
  return ladder.add_player(player_name, bnet_id, char_code, user, admin)

def _remove_player_transaction(ladder, player, force):
  return ladder.remove_player(player, force)

def _add_match_transaction(ladder, user_player, replay_data, filename):
  return ladder.add_match(user_player, replay_data, filename)
