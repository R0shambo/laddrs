import cgi
import datetime
import urllib
import wsgiref.handlers
import os
import pprint

import models

from google.appengine.ext import blobstore
from google.appengine.ext.webapp import blobstore_handlers
from google.appengine.ext.webapp import template
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

from sc2replaylib.replay import Replay, Team, Player


class MainPage(webapp.RequestHandler):
  def get(self):
    ladder_name = self.request.get('l')
    if not ladder_name:
      ladder_name = 'default_ladder'

    all_players = db.GqlQuery("SELECT * "
                          "FROM PT_SC2Player "
                          "WHERE ANCESTOR IS :1 "
                          "ORDER BY elo_rating, joined DESC",
                          ladder_key(ladder_name))

    players = []
    new_players = []
    for player in all_players:
      if player.games_played > 0:
        players.append(player)
      else:
        new_players.append(player)

    # Determine if user is a member of the ladder.
    user = users.get_current_user()
    user_player = None
    if user:
      for player in players:
        if player.account == user:
          player.this_is_you = True
          user_player = player
      for player in new_players:
        if player.account == user:
          player.this_is_you = True
          user_player = player
      auth_url = users.create_logout_url(self.request.uri)
      auth_url_linktext = 'Logout'
    else:
      auth_url = users.create_login_url(self.request.uri)
      auth_url_linktext = 'Login'


    template_values = {
      'ladder_name': ladder_name,
      'user': user,
      'user_player': user_player,
      'players': players,
      'new_players': new_players,
      'auth_url': auth_url,
      'auth_url_linktext': auth_url_linktext,
      'upload_url': blobstore.create_upload_url('/upload'),
    }

    path = os.path.join(os.path.dirname(__file__), 'index.html')
    self.response.out.write(template.render(path, template_values))


class JoinHandler(webapp.RequestHandler):
  def post(self):
    user = users.get_current_user()
    if not user:
      self.response.out.write("You must be signed in.")
      return

    ladder_name = self.request.get('l')
    if not ladder_name:
      ladder_name = 'default_ladder'
    handle = self.request.get('handle')

    if not handle:
      self.response.out.write("You must specify a Handle.")
      return

    # error if handle already exists, otherwise create it.
    player = db.get(db.Key.from_path("PT_SC2Player", handle.lower(),
                                     parent=ladder_key(ladder_name)))
    if player:
      self.response.out.write("Handle %s already exists." % handle)
      return

    # yay create player!
    player = PT_SC2Player(key_name=handle.lower(), handle=handle,
                          parent=ladder_key(ladder_name),
                          account=user, elo_rating=1600, games_played=0)

    player.put()
    self.redirect('/?' + urllib.urlencode({'l': ladder_name}))


class UploadHandler(blobstore_handlers.BlobstoreUploadHandler):
  def post(self):
    for upload in self.get_uploads():
      replay = PT_SC2Replay(author=users.get_current_user(),
                            blob_key=upload.key(), filename=upload.filename)
      blob_reader = blobstore.BlobReader(upload.key())
      parsed_replay = Replay(blob_reader)
      replay.mapname = parsed_replay.map_human_friendly()
      replay.date = parsed_replay.timestamp()
      if parsed_replay.game_teams() == "1v1":
        if parsed_replay.teams[0].players[0].outcome() == "Won":
          replay.winner = parsed_replay.teams[0].players[0].handle()
          replay.loser = parsed_replay.teams[1].players[0].handle()
        elif parsed_replay.teams[1].players[0].outcome() == "Won":
          replay.winner = parsed_replay.teams[1].players[0].handle()
          replay.loser = parsed_replay.teams[0].players[0].handle()
      db.put(replay)
    self.redirect('/')


class ReplayInfo(webapp.RequestHandler):
  def get(self, blob_key):
    blob_key = str(urllib.unquote(blob_key))
    blob_info = blobstore.BlobInfo.get(blob_key)
    blob_reader = blobstore.BlobReader(blob_key)
    replay = Replay(blob_reader)
    
    # the version of starcraft that this replay was recorded on
    self.response.out.write('This replay is version ' + '.'.join([str(n) for n in replay.version()]) + "\n")
    self.response.out.write('The revision number is ' + str(replay.revision()) + "\n")
    
    #raw data on the replay file-----
    self.response.out.write(pprint.pformat(replay.parsers[replay.FILES['details']].parse()))
    self.response.out.write(pprint.pformat(replay.parsers[replay.FILES['attributes']].parse()))
    
    #-------
    
    # run output of game_speed through human readable list of values
    self.response.out.write(replay.game_speed() + "\n")
    
    # raw output of game_teams attribute (could be ugly-ish)
    self.response.out.write(replay.game_teams(True) + "\n")
    
    # running output through another included list
    self.response.out.write(replay.game_matching() + "\n")
    
    # datetime object returned with date match was played
    self.response.out.write(replay.timestamp())
    self.response.out.write("\n")
    
    # timezone offset as integer
    self.response.out.write(replay.timezone_offset())
    self.response.out.write("\n")
    
    
    #-------
    
    #pull team information
    self.response.out.write("there are %d teams" % len(replay.teams) + "\n")
    
    # pull team win/loss info
    self.response.out.write("Team 1 %s" % replay.teams[0].outcome() + "\n")
    self.response.out.write("Team 2 %s" % replay.teams[1].outcome() + "\n")
    
    
    #-------
    
    self.response.out.write("There are %d players on team 1" % len(replay.teams[0].players) + "\n")
    
    player = replay.teams[0].players[0]
    self.response.out.write("%s the %s %s playing as the %s %s" % (
      player.handle(),
      player.type(),
      player.outcome(),
      player.color_name(),
      player.race()) + "\n")


class ReplayDebugInfo(webapp.RequestHandler):
  def get(self, blob_key):
    blob_key = str(urllib.unquote(blob_key))
    blob_info = blobstore.BlobInfo.get(blob_key)
    blob_reader = blobstore.BlobReader(blob_key)
    replay = Replay(blob_reader)

    self.response.headers['Content-Type'] = 'text/plain'
    
    # the version of starcraft that this replay was recorded on
    self.response.out.write('This replay is version ' + '.'.join([str(n) for n in replay.version()]) + "\n")
    self.response.out.write('The revision number is ' + str(replay.revision()) + "\n")
    
    #raw data on the replay file-----
    self.response.out.write(pprint.pformat(replay.parsers[replay.FILES['details']].parse()))
    self.response.out.write(pprint.pformat(replay.parsers[replay.FILES['attributes']].parse()))
    
    #-------
    
    # run output of game_speed through human readable list of values
    self.response.out.write(replay.game_speed() + "\n")
    
    # raw output of game_teams attribute (could be ugly-ish)
    self.response.out.write(replay.game_teams(True) + "\n")
    
    # running output through another included list
    self.response.out.write(replay.game_matching() + "\n")
    
    # datetime object returned with date match was played
    self.response.out.write(replay.timestamp())
    self.response.out.write("\n")
    
    # timezone offset as integer
    self.response.out.write(replay.timezone_offset())
    self.response.out.write("\n")
    
    
    #-------
    
    #pull team information
    self.response.out.write("there are %d teams" % len(replay.teams) + "\n")
    
    # pull team win/loss info
    self.response.out.write("Team 1 %s" % replay.teams[0].outcome() + "\n")
    self.response.out.write("Team 2 %s" % replay.teams[1].outcome() + "\n")
    
    
    #-------
    
    self.response.out.write("There are %d players on team 1" % len(replay.teams[0].players) + "\n")
    
    player = replay.teams[0].players[0]
    self.response.out.write("%s the %s %s playing as the %s %s" % (
      player.handle(),
      player.type(),
      player.outcome(),
      player.color_name(),
      player.race()) + "\n")
    player = replay.teams[1].players[0]
    self.response.out.write("%s the %s %s playing as the %s %s" % (
      player.handle(),
      player.type(),
      player.outcome(),
      player.color_name(),
      player.race()) + "\n")
    

application = webapp.WSGIApplication([
  ('/', MainPage),
  ('/join', JoinHandler),
  ('/upload', UploadHandler),
  ('/debuginfo/([^/]+)?', ReplayDebugInfo),
  ('/info/([^/]+)?', ReplayInfo),
], debug=True)


def main():
  run_wsgi_app(application)


if __name__ == '__main__':
  main()