import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'settings'

from google.appengine.dist import use_library
use_library('django', '1.2')

import cgi

from google.appengine.ext.webapp import template
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

from laddrslib import util
from laddrslib import models
from laddrslib.models import SC2Ladder

class MainPage(webapp.RequestHandler):
  def get(self):
    template_values = util.add_user_tmplvars(self, {
      'create_ladder_invite_only': True,
    })

    path = os.path.join(os.path.dirname(__file__), 'tmpl/create_ladder.html')
    self.response.out.write(template.render(path, template_values))

  def post(self):
    user = users.get_current_user()
    if not user:
      self.redirect(users.create_login_url(self.request.uri))
      return
    name = self.request.get('name')
    region = self.request.get('region')
    description = self.request.get('description')
    public = bool(self.request.get('public'))
    invite_only = bool(self.request.get('invite_only'))
    player_name = self.request.get('player_name')
    player_bnet_id = self.request.get('player_bnet_id')
    player_code = self.request.get('player_code')
    errormsg = None

    try:
      ladder = SC2Ladder.create_ladder(user, name, region, description, public,
              invite_only, player_name, player_bnet_id, player_code)
      # yay ladder created!
      if ladder:
         self.redirect('/ladder/%s' % ladder.get_ladder_key())
         return
      else:
        errormsg = "Umm... not quite sure what has gone wrong."
    except models.LadderNameMissing:
      errormsg = "Derp! Ladder Name is required, Silly."
    except models.InvalidName:
      errormsg = "I see what you are doing there, and I don't like it."
    except models.InvalidRegion:
      errormsg = "Invalid Battle.net Region specified. Are you h4x0ring?"
    except models.LadderDescriptionMissing:
      errormsg = "Description is required. The least you could do is fill in something tweet worthy."
    except models.PlayerNameMissing:
      errormsg = "Can't have a ladder without players, so please fill-in your Starcraft 2 Character Name."
    except models.CharCodeMissing:
      errormsg = "Your Battle.net Character Code is required so other members of the ladder can find you. It will only be shown to members of the ladder."
    except models.InvalidCharCode:
      errormsg = "Character Code must be a three-digit number."
    except models.PlayerBNetIdMissing:
      errormsg = "Your Battle.net ID is required to verify replay uploads."
    except models.InvalidPlayerBNetId:
      errormsg = "Battle.Net ID must be a six or seven digit number."
    except models.LadderAlreadyExists:
      errormsg = "There is already a ladder with the name %s." % name

    template_values = util.add_user_tmplvars(self, {
      'errormsg': errormsg,
      'create_ladder_name': name,
      'create_ladder_region': region,
      'create_ladder_description': description,
      'create_ladder_invite_only': invite_only,
      'create_ladder_public': public,
      'join_ladder_player_name': player_name,
      'join_ladder_player_bnet_id': player_bnet_id,
      'join_ladder_player_code': player_code,
    })

    path = os.path.join(os.path.dirname(__file__), 'tmpl/create_ladder.html')
    self.response.out.write(template.render(path, template_values))

application = webapp.WSGIApplication([
  ('/create_ladder', MainPage),
], debug=True)


def main():
  run_wsgi_app(application)


if __name__ == '__main__':
  main()
