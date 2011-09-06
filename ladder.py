import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'settings'

from google.appengine.dist import use_library
use_library('django', '1.2')

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
    ladder_key = str(urllib.unquote(ladder_key))
    ladder = SC2Ladder.get_ladder(ladder_key)

    # Return 404 if ladder could not be found.
    if not ladder:
      self.error(404)
      self.response.out.write("<h1>Ladder Not Found</h1>")
      return

    user = users.get_current_user()

    # Special handling for private ladders
    if not ladder.public and not user:
      self.redirect(users.create_login_url(self.request.uri))
      return

    (players, new_players, user_player) = ladder.get_players(user)
    matches = None
    if ladder.matches_played:
      matches = ladder.get_matches(user)

    template_values = util.add_user_tmplvars(self, {
      'ladder': ladder,
      'user_player': user_player,
      'players': players,
      'new_players': new_players,
      'matches': matches,
    })

    path = os.path.join(os.path.dirname(__file__), 'tmpl/ladder.html')
    self.response.out.write(template.render(path, template_values))


application = webapp.WSGIApplication([
  ('/ladder/([^/]+)?', MainPage),
], debug=True)


def main():
  run_wsgi_app(application)


if __name__ == '__main__':
  main()
