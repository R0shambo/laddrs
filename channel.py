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
from laddrslib.models import SC2Ladder, SC2Player, SC2Match, ChatChannel

from django.utils import simplejson

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

    if action == 'ping':
      self.response.out.write(ChatChannel.ping(ladder, user, self.request.get('ssp')))
    elif action == 'get-token':
      self.response.out.write(ChatChannel.get_token(ladder, user_player,
          self.request.get('refresh')))
    elif action == 'get-chat-history':
      self.response.out.write(ChatChannel.get_chat_history(ladder, user_player,
          self.request.get('last_chat_msg')))
    elif action == 'send-chat':
      self.response.out.write(ChatChannel.send_chat(ladder, user_player, self.request.get('m')))
    elif action == 'get-ladder-data':
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
      path = os.path.join(os.path.dirname(__file__), 'tmpl/players.html')
      player_data = template.render(path, template_values)
      path = os.path.join(os.path.dirname(__file__), 'tmpl/match_history.html')
      match_data = template.render(path, template_values)
      json_obj = {
        'players': player_data,
        'match_history': match_data,
      }
      self.response.out.write(simplejson.dumps(json_obj))
    else:
      self.response.out.write("NOK")


class ChannelConnected(webapp.RequestHandler):
  def post(self):
    ChatChannel.client_connected(self.request.get('from'))


class ChannelDisconnected(webapp.RequestHandler):
  def post(self):
    ChatChannel.client_disconnected(self.request.get('from'))


application = webapp.WSGIApplication([
  ('/channel/([^/]+)/([^/]+)', MainPage),
  ('/_ah/channel/connected/', ChannelConnected),
  ('/_ah/channel/disconnected/', ChannelDisconnected),
], debug=True)


def main():
  run_wsgi_app(application)


if __name__ == '__main__':
  main()
