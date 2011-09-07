import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'settings'

from google.appengine.dist import use_library
use_library('django', '1.2')

import datetime
import pprint
import re
import urllib

from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

from laddrslib import util
from laddrslib.models import SC2Ladder, SC2Player, SC2Match

class MainPage(webapp.RequestHandler):
  def get(self, ladder_key):
    self.redirect("/")

  def post(self, ladder_key):
    ladder_key = str(urllib.unquote(ladder_key))
    ladder = SC2Ladder.get_ladder(ladder_key)

    # Return 404 if ladder could not be found.
    if not ladder:
      self.error(404)
      self.response.out.write("<h1>Ladder Not Found</h1>")
      return

    user = users.get_current_user()
    if not user:
      self.redirect(
          users.create_login_url("/ladder/%s" % ladder.get_ladder_key))
      return

    # See if this user already belongs to this ladder.
    user_player = ladder.get_user_player(user)

    if not user_player:
      self.error(403)
      self.response.out.write("<h1>Upload Forbidden</h1>")

    filename = None
    if hasattr(self.request.POST["replay_file"], 'filename'):
      filename = self.request.POST["replay_file"].filename

    if util.csrf_protect(self):
      try:
        match = ladder.add_match(user_player,
            self.request.get('replay_file'), filename,
            force=self.request.get('force_upload'))
        if match:
          self.redirect('/ladder/%s' % ladder.get_ladder_key())
          util.set_butter(
              "Match replay accepted. Player rankings adjusted.")
          util.track_pageview('/goal/match_upload.html')
          return
        else:
          errormsg = "Umm... not quite sure what has gone wrong."
      except SC2Match.ReplayParseFailed:
        errormsg = "Unable to parse uploaded replay file."
      except SC2Match.TooManyPlayers, e:
        errormsg = "Only 1v1 replays allowed. Uploaded replay has %d players." % e.args
      except SC2Match.ReplayHasNoWinner:
        errormsg = "Replay has no winner."
      except SC2Match.WinnerNotInLadder, e:
        errormsg = "Winner (%s) is not a member of the ladder." % e.args
      except SC2Match.LoserNotInLadder, e:
        errormsg = "Loser (%s) is not a member of the ladder." % e.args
      except SC2Match.NotReplayOfUploader:
        errormsg = "You may only upload your own replays."
      except SC2Match.MatchAlreadyExists:
        errormsg = "This match has already been uploaded."
    else:
      errormsg = "Session timed out."

    template_values = util.add_user_tmplvars(self, {
      'errormsg': errormsg,
      'ladder': ladder,
      'user_player': user_player,
    })

    path = os.path.join(os.path.dirname(__file__), 'tmpl/upload.html')
    self.response.out.write(template.render(path, template_values))


application = webapp.WSGIApplication([
  ('/upload/([^/]+)?', MainPage),
], debug=True)


def main():
  run_wsgi_app(application)


if __name__ == '__main__':
  main()
