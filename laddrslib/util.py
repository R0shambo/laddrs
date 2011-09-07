import base64
import os

from google.appengine.api import memcache
from google.appengine.api import users

MC_EXP_LONG=86400
MC_BUTTER='butter'
MC_CSRF='csrf-tokens'

def add_user_tmplvars(handler, tmplvars):
  user = users.get_current_user()
  tmplvars['user'] = user
  tmplvars['csrf_token'] = get_csrf_token()
  tmplvars['site_admin'] = users.is_current_user_admin()
  tmplvars['butter'] = get_butter()
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
  if (get_csrf_token() and
      handler.request.get('csrf_token') == get_csrf_token()):
    return True
  return False

def set_butter(msg):
  user = users.get_current_user()
  if user:
    memcache.set(user.user_id(), msg, namespace=MC_BUTTER, time=MC_EXP_LONG)
    return True

def get_butter():
  user = users.get_current_user()
  if user:
    butter = memcache.get(user.user_id(), namespace=MC_BUTTER)
    if butter:
      memcache.delete(user.user_id(), namespace=MC_BUTTER)
      return butter
