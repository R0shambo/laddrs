import cgi
import datetime
import os
import urllib
import wsgiref.handlers
import pprint

from google.appengine.ext import blobstore
from google.appengine.ext.webapp import blobstore_handlers
from google.appengine.ext.webapp import template
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

from laddrslib import util
from laddrslib.models import SC2Ladder


class MainPage(webapp.RequestHandler):
  def get(self):
    template_values = util.add_user_tmplvars(self, {
      'user_ladders': SC2Ladder.get_ladders_for_user(users.get_current_user()),
      'public_ladders': SC2Ladder.get_public_ladders(),
      'create_ladder_invite_only': True,
    })

    path = os.path.join(os.path.dirname(__file__), 'tmpl/index.html')
    self.response.out.write(template.render(path, template_values))


class WarmUp(webapp.RequestHandler):
  def get(self):
    self.response.out.write("OK")


application = webapp.WSGIApplication([
  ('/', MainPage),
  ('/_ah/warmup', WarmUp),
], debug=True)


def main():
  run_wsgi_app(application)


if __name__ == '__main__':
  main()
