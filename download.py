import re
import urllib

from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

from laddrslib import util
from laddrslib.models import SC2Ladder, SC2Player, SC2Match

class DownloadReplay(webapp.RequestHandler):
  def get(self, ladder_name, match_key):
    ladder_key = str(urllib.unquote(ladder_name))
    ladder = SC2Ladder.get_ladder_by_name(ladder_name)
    # Return 404 if ladder could not be found.
    if not ladder:
      self.error(404)
      self.response.out.write("<h1>Match Replay Not Found</h1>")
      return
    match = ladder.get_match(str(urllib.unquote(match_key)))

    # Return 404 if ladder could not be found.
    if not match:
      self.error(404)
      self.response.out.write("<h1>Match Replay Not Found</h1>")
      return

    user = users.get_current_user()

    # Special handling for private ladders
    if not ladder.public:
      if not user:
        self.redirect(users.create_login_url(self.request.uri))
        return
      if not ladder.get_user_player(user):
        self.error(404)
        self.response.out.write("<h1>Match Replay Not Found</h1>")
        return

    self.response.headers['Content-Type'] = 'application/octet-stream'
    self.response.out.write(match.replay)


class DownloadZip(webapp.RequestHandler):
  def get(self, ladder_name):
    ladder_key = str(urllib.unquote(ladder_name))
    ladder = SC2Ladder.get_ladder_by_name(ladder_name)
    # Return 404 if ladder could not be found.
    if not ladder:
      self.error(404)
      self.response.out.write("<h1>Ladder Not Found</h1>")
      return

    user = users.get_current_user()

    # Special handling for private ladders
    if not ladder.public:
      if not user:
        self.redirect(users.create_login_url(self.request.uri))
        return
      if not ladder.get_user_player(user):
        self.error(404)
        self.response.out.write("<h1>Ladder Not Found</h1>")
        return

    zip = ladder.get_matches_zipfile()
    self.response.headers['Content-Type'] = 'application/zip'
    self.response.out.write(zip)

application = webapp.WSGIApplication([
  ('/download/([^/]+)/([^/]+)/[^/.]+\.SC2Replay', DownloadReplay),
  ('/download/([^/]+).zip', DownloadZip),
], debug=True)


def main():
  run_wsgi_app(application)


if __name__ == '__main__':
  main()
