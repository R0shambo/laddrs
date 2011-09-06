import datetime
import random
import re
import StringIO

from google.appengine.api import memcache
from google.appengine.ext import blobstore
from google.appengine.ext import db

from sc2ranks import Sc2Ranks
from sc2replaylib.replay import Replay

MC_EXP_SHORT=60
MC_EXP_MED=1200
MC_EXP_LONG=86400

MC_PL="public-ladders"
MC_L4U="ladders-for-user"
MC_P4L="players-for-ladder"
MC_SC2RP="sc2rank-player"


DEFAULT_ELO_RATING=1600

REGION_RE = re.compile("^(us|eu|kr|tw|sea|ru|la)$")

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

  @classmethod
  def gen_ladder_invite_code(cls):
    return random.getrandbits(17)
  
  @classmethod
  def create_ladder(cls, user, ladder_name, region, description, public,
      invite_only, player_name, bnet_id, char_code):
  
    if db.is_in_transaction():  
      # sanity checks.
      if not ladder_name:
        raise LadderNameMissing
      if "<" in ladder_name or ">" in ladder_name:
        raise InvalidName
      if not description:
        raise LadderDescriptionMissing
      if not REGION_RE.match(region):
        raise InvalidRegion
    
      # check if ladder already exists.
      ladder = cls.get_ladder_by_name(ladder_name)
      if ladder:
        raise LadderAlreadyExists
    
      ladder = SC2Ladder(
          key_name=ladder_name.strip().lower(),
          name=ladder_name.strip(),
          region=region,
          description=description,
          public=public,
          invite_only=invite_only,
          invite_code=cls.gen_ladder_invite_code(),
          matches_played=0,
          players=0)
    
      ladder.put()
    
      player = SC2Player.create_player(
          user, ladder, player_name, bnet_id, char_code, admin=True)
    
      return ladder

    # if we got this far, it means we are not inside a transaction, start one.
    rv = db.run_in_transaction(_create_ladder_transaction,
        user, ladder_name, region, description, public, invite_only,
        player_name, bnet_id, char_code)
    memcache.delete(MC_PL)
    memcache.delete(user.user_id(), namespace=MC_L4U)
    return rv
  
  @classmethod
  def get_ladder(cls, ladder_key):
    """Retrieves a SC2Ladder object from the datastore."""
    return db.get(ladder_key)
  
  @classmethod
  def get_ladder_by_name(cls, ladder_name):
    """Retrieves a SC2Ladder object from the datastore."""
    return cls.get_ladder(db.Key.from_path(
        'SC2Ladder', ladder_name.strip().lower()))
  
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
      players = SC2Player.gql("WHERE user_id = :1", user.user_id())
      for player in players:
        ladders.append(player.get_ladder())
      # try adding to memcache
      if (not memcache.add(
              user.user_id(), ladders, namespace=MC_L4U, time=MC_EXP_MED)
          and retry):
        # if we were unable to add to memcache, it's possible another process
        # did and it had more up-to-date information (new player added for
        # instance). So let's try again using that.
        ladders = cls.get_ladders_for_user(user, retry=False)
    return ladders

  def get_player(self, player_name, bnet_id):
    """Retrieves a SC2Ladder object from the datastore."""
    return db.get(db.Key.from_path(
        'SC2Ladder', self.name.lower(),
        'SC2Player', SC2Player.player_key(player_name, bnet_id)))
  
  def get_players(self, user=None):
  
    all_players = memcache.get(self.key().name(), namespace=MC_P4L)
    if not all_players:
      all_players = SC2Player.gql(
          "WHERE ANCESTOR IS :1 ORDER BY elo_rating, joined DESC", self.key())
      memcache.add(
          self.key().name(), all_players, namespace=MC_P4L, time=MC_EXP_MED)
  
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
      q = cls.gql(
          "WHERE public = True ORDER BY matches_played DESC, players DESC")
      ladders = q.fetch(100)
      # try adding to memcache, use short expiration as this may change frequently
      memcache.add(MC_PL, ladders, time=MC_EXP_SHORT)
    return ladders

  def find_match(self, winner, loser, timestamp):
    match_key = SC2Match.match_key_name(winner, loser, timestamp)
    return db.get(db.Key.from_path(
        'SC2Ladder', self.name.lower(),
        'SC2Player', SC2Match.match_key(winner, loser, timestamp))
    


class SC2Player(db.Model):
  """Ladder players."""
  name = db.StringProperty(required=True)
  bnet_id = db.StringProperty(required=True)
  code = db.StringProperty(required=True)
  user_id = db.StringProperty(required=True)
  joined = db.DateTimeProperty(auto_now_add=True)
  admin = db.BooleanProperty()
  elo_rating = db.IntegerProperty(required=True)
  matches_played = db.IntegerProperty(required=True)
  wins = db.IntegerProperty(required=True)
  losses = db.IntegerProperty(required=True)
  last_played = db.DateTimeProperty()

  @classmethod
  def player_key(cls, player_name, bnet_id):
    return "%s/%s" % (player_name.lower(), bnet_id)

  @classmethod
  def create_player(cls, user, ladder, player_name, bnet_id, char_code,
      admin=False):
    if db.is_in_transaction():
      # sanity checks
      if not player_name:
        raise PlayerNameMissing
      if "<" in player_name or ">" in player_name or "/" in player_name:
        raise InvalidName
      if not char_code:
        raise CharCodeMissing
      if not char_code.isdigit():
        raise InvalidCharCode
      if not bnet_id:
        raise PlayerBNetIdMissing
      if not bnet_id.isdigit():
        raise InvalidPlayerBNetId
    
      if cls.get_player(ladder.name, player_name, bnet_id):
        raise PlayerAlreadyExists
    
      player = SC2Player(
          parent=ladder,
          key_name=cls.player_key(player_name, bnet_id),
          name=player_name,
          bnet_id=bnet_id,
          code=char_code,
          user_id=user.user_id(),
          elo_rating=DEFAULT_ELO_RATING,
          matches_played=0,
          wins=0,
          losses=0,
          admin=admin)
    
      player.put()
      ladder.players = ladder.players + 1
      ladder.put()
      return player

    # if we got this far, it means we are not inside a transaction, start one.
    rv = db.run_in_transaction(_create_player_transaction,
        user, ladder, player_name, bnet_id, char_code, admin)
    memcache.delete(user.user_id(), namespace=MC_L4U)
    memcache.delete(ladder.key().name(), namespace=MC_P4L)
    return rv
  
  @classmethod
  def get_player(cls, ladder_name, player_name, bnet_id):
    """Retrieves a SC2Ladder object from the datastore."""
    return db.get(db.Key.from_path(
        'SC2Ladder', ladder_name.lower(),
        'SC2Player', cls.player_key(player_name, bnet_id)))

  def get_ladder(self):
    return db.get(self.parent().key())
  
  def sc2rank_player_key(self):
    return "%s/%s/%s" % (self.parent().region, self.name, self.bnet_id)
  
  def get_sc2rank(self):
    if not self.bnet_id:
      return
    if not hasattr(self, '_base_character') or not self._base_character:
      self._base_character = memcache.get(self.sc2rank_player_key(),
                                          namespace=MC_SC2RP)
    if not self._base_character:
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
          pass


class SC2Match(db.Model):
  """Matches are consist of a replay (stored in BlobStore) plus details
     parsed from the replay."""
  uploader = db.ReferenceProperty(SC2Player, collection_name='uploads')
  replay = db.BlobProperty(required=True)
  uploaded = db.DateTimeProperty(auto_now_add=True)
  winner = db.ReferenceProperty(SC2Player, collection_name='w_matches')
  loser = db.ReferenceProperty(SC2Player, collection_name='l_matches')
  mapname = db.StringProperty(required=True)
  match_date_utc = db.DateTimeProperty(required=True)
  match_date_local = db.DateTimeProperty(required=True)
  duration = db.StringProperty(required=True)
  version = db.StringProperty(required=True)

  class ReplayParseFailed(Exception):
    pass

  @classmethod
  def create_match(cls, ladder, user_player, replay_data):
    if db.is_in_transaction():
      replay_file = StringIO.StringIO(replay_data)
      replay = None
      try:
        replay = Replay(replay_file)
      except:
        raise ReplayParseFailed
  
      # replays must be 1v1 since this is a 1v1 ladder site afterall.
      if replay.game_teams(True) != '1v1':
        raise ReplayNot1v1
      
      # determine the winner and loser players.
      if replay.teams[0].players[0].outcome() == 'Won':
        replay_winner = replay.teams[0].players[0]
        replay_loser = replay.teams[1].players[0]
      elif replay.teams[1].players[0].outcome() == 'Won':
        replay_winner = replay.teams[1].players[0]
        replay_loser = replay.teams[0].players[0]
      else:
        raise ReplayHasNoWinner
      
      # now check that players are in the ladder.
      winner = ladder.get_player(replay_winner.handle(), replay_winner.bnet_id())
      if not winner:
        raise WinnerNotInLadder(
            "%s/%s" % (replay_winner.handle(), replay_winner.bnet_id()))
      loser = ladder.get_player(replay_loser.handle(), replay_loser.bnet_id())
      if not loser:
        raise LoserNotInLadder(
            "%s/%s" % (replay_loser.handle(), replay_loser.bnet_id()))
    
      # make sure that uploader is either the winner or loser.
      if user_player != winner and user_player != loser:
        raise NotReplayOfUploader
  
      # make sure this replay was not previously uploaded
      existing_match = ladder.find_match(winner, loser, replay.timestamp())
      if existing_match:
        raise MatchAlreadyExists

      winner.matches_played = winner.matches_played + 1
      winner.wins = winner.wins + 1
      winner.last_played = datetime.datetime.now()

      loser.matches_played = loser.matches_played + 1
      loser.losses = loser.losses + 1
      loser.last_played = datetime.datetime.now()


    # if we got this far, it means we are not inside a transaction, start one.
    rv = db.run_in_transaction(_create_match_transaction,
        ladder, user_player, replay_data)
    return rv

  @classmethod
  def match_key(cls, winner, loser, timestamp):
    return "%s|%s|%s" % (
        winner.key().name(), loser.key().name(), str(timestamp))
    
    
    





class InvalidName(Exception):
  pass

class InvalidPlayerBNetId(Exception):
  pass

class InvalidCharCode(Exception):
  pass

class InvalidRegion(Exception):
  pass

class LadderAlreadyExists(Exception):
	pass

class LadderDescriptionMissing(Exception):
  pass

class LadderNameMissing(Exception):
  pass

class LadderNotFound(Exception):
  pass

class PlayerBNetIdMissing(Exception):
  pass

class CharCodeMissing(Exception):
  pass

class PlayerNameMissing(Exception):
  pass

class PlayerAlreadyExists(Exception):
	pass


def _create_ladder_transaction(user, ladder_name, region, description, public,
    invite_only, player_name, bnet_id, char_code):
  return SC2Ladder.create_ladder(user, ladder_name, region, description, public,
      invite_only, player_name, bnet_id, char_code)

def _create_player_transaction(user, ladder, player_name, bnet_id, char_code,
    admin):
  return SC2Player.create_player(user, ladder, player_name, bnet_id, char_code,
    admin)

def _create_match_transaction(ladder, user_player, replay_data):
  return SC2Match.create_match(ladder, user_player, replay_data)