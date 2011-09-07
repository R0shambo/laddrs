import base64
import os

from google.appengine.api import memcache
from google.appengine.api import users

MC_EXP_LONG=86400
MC_CSRF='csrf-tokens'

def add_user_tmplvars(handler, tmplvars):
  user = users.get_current_user()
  tmplvars['user'] = user
  tmplvars['csrf_token'] = get_csrf_token()
  if user:
    tmplvars['auth_url'] = users.create_logout_url(handler.request.uri)
    tmplvars['auth_url_linktext'] = 'Logout %s' % user.nickname()
  else:
    tmplvars['auth_url'] = users.create_login_url(handler.request.uri)
    tmplvars['auth_url_linktext'] = 'Login'

  return tmplvars

def get_csrf_token():
  user = users.get_current_user()
  if user:
    token = memcache.get(user.user_id(), namespace=MC_CSRF)
    if token:
      return token
    token = base64.urlsafe_b64encode(os.urandom(12))
    memcache.set(user.user_id(), token, namespace=MC_CSRF, time=MC_EXP_LONG)
    return token

def csrf_protect(handler):
  if handler.request.get('csrf_token') == get_csrf_token():
    return True
  return False
