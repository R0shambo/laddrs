import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'settings'

from google.appengine.dist import use_library
use_library('django', '1.2')

import datetime
import logging
import pprint
import re
import urllib
import StringIO

from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

from sc2replaylib.replay import Replay

def render_form():
  return """
      <form action="/replay_debug" method="POST" enctype="multipart/form-data">
      <div>Replay File: <input type="file" name="replay_file">
       <input type="submit" name="submit" value="Upload!"></div>
     </form>"""


class MainPage(webapp.RequestHandler):
  def get(self):
    self.response.out.write(render_form())

  def post(self):
    user = users.get_current_user()
    if not user:
      self.redirect(users.create_login_url("/"))
      return

    self.response.out.write(render_form())

    replay_data = self.request.get('replay_file')
    replay_file = StringIO.StringIO(replay_data)
    
    replay = Replay(replay_file)
    
    try:
      self.response.out.write("<pre>Filename: %s\n" % self.request.POST["replay_file"].filename)
      
      # the version of starcraft that this replay was recorded on
      self.response.out.write('This replay is version ' + '.'.join([str(n) for n in replay.version()]) + "\n")
      self.response.out.write('The revision number is ' + str(replay.revision()) + "\n")
      
      # run output of game_speed through human readable list of values
      self.response.out.write("game speed: " + replay.game_speed() + "\n")
      
      # raw output of game_teams attribute (could be ugly-ish)
      self.response.out.write("game teams: " + replay.game_teams(True) + "\n")
      
      # running output through another included list
      self.response.out.write("match mode: " + replay.game_matching() + "\n")
      
      # datetime object returned with date match was played
      self.response.out.write("utc date: ")
      self.response.out.write(replay.timestamp())
      self.response.out.write("\n")
      # datetime object returned with date match was played
      self.response.out.write("local date: ")
      self.response.out.write(replay.timestamp_local())
      self.response.out.write("\n")
          
      self.response.out.write("duration: %s\n" % str(datetime.timedelta(seconds=replay.duration())))
      
      
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
  
      self.response.out.write("==================== RAW ======================\n")
      #raw data on the replay file-----
      self.response.out.write(pprint.pformat(replay.parsers['header'].parse()))
      self.response.out.write(pprint.pformat(replay.parsers[replay.FILES['details']].parse()))
      self.response.out.write(pprint.pformat(replay.parsers[replay.FILES['attributes']].parse()))
  
      self.response.out.write('</pre>')
    except:
      logging.error(pprint.pformat(replay.parsers['header'].parse()))
      logging.error(pprint.pformat(replay.parsers[replay.FILES['details']].parse()))
      logging.error(pprint.pformat(replay.parsers[replay.FILES['attributes']].parse()))
      raise

application = webapp.WSGIApplication([
  ('/replay_debug', MainPage),
], debug=True)


def main():
  run_wsgi_app(application)


if __name__ == '__main__':
  main()
