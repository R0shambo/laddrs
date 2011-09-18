import datetime
import os
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
  def get(self, ladder_name):
    self.redirect("/")

  def post(self, ladder_name):
    ladder = SC2Ladder.get_ladder_by_name(ladder_name)

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

    rejected = []

    if util.csrf_protect(self):
      (accepted, rejected) = ladder.add_matches(user_player,
          self.request.params.getall('replay_file'),
          force=self.request.get('force_upload'))
      if accepted and len(accepted) > 0:
        util.set_onetime('uploads_accepted', accepted)
        util.set_onetime('uploads_rejected', rejected)
        s = 's' if len(accepted) > 1 else ''
        util.set_butter(
            "Match replay%s accepted. Player rankings adjusted." % s)
        util.track_event('ladder', 'match-upload', ladder.get_ladder_key(), value=len(accepted))
        self.redirect('/ladder/%s#upload' % ladder.get_ladder_key())
        return
      else:
        s = 's' if len(rejected) > 1 else ''
        errormsg = "No replay%s accepted." % s

    else:
      errormsg = "Session timed out."

    template_values = util.add_user_tmplvars(self, {
      'errormsg': errormsg,
      'ladder': ladder,
      'user_player': user_player,
      'uploads_rejected': rejected,
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
