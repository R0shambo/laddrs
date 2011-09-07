import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'settings'

from google.appengine.dist import use_library
use_library('django', '1.2')

import logging
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
  def get(self, manage, ladder_name):
    ladder_key = str(urllib.unquote(ladder_name))
    ladder = SC2Ladder.get_ladder_by_name(ladder_name)

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

    if self.request.get('quit_ladder'):
      if user_player and util.csrf_protect(self):
        ladder.remove_player(user_player)
      self.redirect(self.request.path)
      return
    
    matches = None
    if ladder.matches_played:
      matches = ladder.get_matches(user)

    manage_ladder = False
    if user_player and user_player.admin and manage:
      manage_ladder = True

    template_values = util.add_user_tmplvars(self, {
      'ladder': ladder,
      'user_player': user_player,
      'players': players,
      'new_players': new_players,
      'matches': matches,
      'manage_ladder': manage_ladder,
    })

    path = os.path.join(os.path.dirname(__file__), 'tmpl/ladder.html')
    self.response.out.write(template.render(path, template_values))

  def post(self, manage, ladder_name):
    ladder_key = str(urllib.unquote(ladder_name))
    ladder = SC2Ladder.get_ladder_by_name(ladder_name)

    # Return 404 if ladder could not be found.
    if not ladder:
      self.error(404)
      self.response.out.write("<h1>Ladder Not Found</h1>")
      return

    user = users.get_current_user()

    # Bounce if not logged in.
    if not user:
      self.redirect(users.create_login_url("/ladder/%s" % ladder.get_ladder_key()))
      return

    # Bounce if user is not an admin.
    user_player = ladder.get_user_player(user)
    if user_player and user_player.admin and util.csrf_protect(self):
      try:
        ladder.update_ladder(
          self.request.get('description'),
          bool(self.request.get('public')),
          bool(self.request.get('invite_only')),
          bool(self.request.get('regen_invite_code')))
      except:
        logging.exception("manage_ladder update failed")

    self.redirect("/ladder/%s" % ladder.get_ladder_key())


application = webapp.WSGIApplication([
  ('/(manage_)?ladder/([^/]+)?', MainPage),
], debug=True)


def main():
  run_wsgi_app(application)


if __name__ == '__main__':
  main()
