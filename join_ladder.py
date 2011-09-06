import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'settings'

from google.appengine.dist import use_library
use_library('django', '1.2')

import cgi
import urllib

from google.appengine.ext.webapp import template
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

from laddrslib import models
from laddrslib import util
from laddrslib.models import SC2Ladder, SC2Player

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
          users.create_login_url("/ladder/%s" % ladder.get_ladder_key()))
      return

    # See if this user already belongs to this ladder.
    if ladder.get_user_player(user):
      self.redirect("/ladder/%s" % ladder.get_ladder_key())
      return

    invite_code = self.request.get('invite_code')
    player_name = self.request.get('player_name')
    bnet_id = self.request.get('player_bnet_id')
    player_code = self.request.get('player_code')
    region = self.request.get('player_region')
    errormsg = None

    if ((ladder.invite_only or not ladder.public) and
        (not invite_code.isdigit() or int(invite_code) != ladder.invite_code)):
      errormsg = "Invalid invite-code entered. Please try again."
    else:
      try:
        player = SC2Player.create_player(
            user, ladder, player_name, bnet_id, player_code, admin=False)
        # yay ladder created!
        if player:
           self.redirect('/ladder/%s' % ladder.get_ladder_key())
           return
        else:
          errormsg = "Umm... not quite sure what has gone wrong."
      except models.PlayerNameMissing:
        errormsg = "Derp! You forgot your Character Name."
      except models.InvalidName:
        errormsg = "I see what you are doing there, and I don't like it."
      except models.CharCodeMissing:
        errormsg = "Your Battle.net Character Code is required so other members of the ladder can find you. It will only be shown to members of the ladder."
      except models.InvalidCharCode:
        errormsg = "Character Code must be a three-digit number."
      except models.PlayerBNetIdMissing:
        errormsg = "Your Battle.net ID is required to verify replay uploads."
      except models.InvalidPlayerBNetId:
        errormsg = "Battle.Net ID must be a six or seven digit number."
      except models.PlayerAlreadyExists:
        errormsg = "Player %s/%s is already a member of this ladder." % (
            player_name, bnet_id)

    template_values = util.add_user_tmplvars(self, {
      'errormsg': errormsg,
      'ladder': ladder,
      'join_ladder_invite_code': invite_code,
      'join_ladder_player_name': player_name,
      'join_ladder_player_code': player_code,
      'join_ladder_player_region': region,
      'join_ladder_player_bnet_id': bnet_id,
    })

    path = os.path.join(os.path.dirname(__file__), 'tmpl/join_ladder.html')
    self.response.out.write(template.render(path, template_values))

application = webapp.WSGIApplication([
  ('/join_ladder/([^/]+)?', MainPage),
], debug=True)


def main():
  run_wsgi_app(application)


if __name__ == '__main__':
  main()
