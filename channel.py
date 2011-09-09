import logging
import os
import re
import time
import urllib

from google.appengine.api import channel
from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.ext.webapp.util import run_wsgi_app

from laddrslib import util
from laddrslib.models import SC2Ladder, SC2Player, SC2Match, Channel

class MainPage(webapp.RequestHandler):
  def get(self, ladder_name, action):
    if users.is_current_user_admin():
      template_values = util.add_user_tmplvars(self, {
      })
      path = os.path.join(os.path.dirname(__file__), 'tmpl/channel.html')
      render_start = time.time()
      self.response.out.write(template.render(path, template_values))
    else:
      self.redirect(users.create_login_url("/"))

  def post(self, ladder_name, action):
    if not ladder_name:
      self.error(404)
      self.response.out.write("<h1>Channel Not Found</h1>")
      return

    ladder = SC2Ladder.get_ladder_by_name(ladder_name)
    # Return 404 if ladder could not be found.
    if not ladder:
      self.error(404)
      self.response.out.write("<h1>Channel Not Found</h1>")
      return

    # Check for valid user.
    user_id = self.request.get('user_id')
    user = users.get_current_user()
    if not user or user.user_id() != user_id:
      self.error(404)
      self.response.out.write("<h1>Channel Not Found</h1>")
      return

    # Check that user is a member of the ladder.
    user_player = ladder.get_user_player(user)
    if not user_player:
      self.error(404)
      self.response.out.write("<h1>Channel Not Found</h1>")
      return

    if action == 'get-token':
      self.response.out.write(Channel.get_token(ladder, user))
      return
    if action == 'get-chat-history':
      logging.info(self.request.get('last_chat_msg'))
      return
    if action == 'send-chat':
      logging.info(self.request.get('m'))
      return

    self.response.out.write("NOK")


class ChannelConnected(webapp.RequestHandler):
  def post(self):
    client_id = self.request.get('from')


class ChannelDisconnected(webapp.RequestHandler):
  def post(self):
    client_id = self.request.get('from')


application = webapp.WSGIApplication([
  ('/channel/([^/]+)/([^/]+)', MainPage),
  ('/_ah/channel/connected/', ChannelConnected),
  ('/_ah/channel/disconnected/', ChannelDisconnected),
], debug=True)


def main():
  run_wsgi_app(application)


if __name__ == '__main__':
  main()
