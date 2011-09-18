import base64
import os

from google.appengine.api import app_identity
from google.appengine.api import memcache
from google.appengine.api import users

MC_EXP_LONG=86400
MC_ONETIME="onetime-vars"
MC_CSRF='csrf-tokens'

def add_user_tmplvars(handler, tmplvars, skip_onetime=False):
  user = users.get_current_user()
  tmplvars['user'] = user
  tmplvars['csrf_token'] = get_csrf_token()
  tmplvars['site_admin'] = users.is_current_user_admin()
  tmplvars['production'] = in_production()
  tmplvars['app_version_id'] = os.getenv('CURRENT_VERSION_ID').replace('-', '.')
  if not skip_onetime:
    tmplvars['butter'] = get_butter()
    tmplvars['track_event'] = get_track_event()
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

def set_onetime(name, msg):
  user = users.get_current_user()
  if user:
    memcache.set("%s|%s" % (user.user_id(), name), msg, namespace=MC_ONETIME)
    return True

def get_onetime(name):
  user = users.get_current_user()
  if user:
    msg = memcache.get("%s|%s" % (user.user_id(), name), namespace=MC_ONETIME)
    if msg:
      memcache.delete("%s|%s" % (user.user_id(), name), namespace=MC_ONETIME)
      return msg

def set_butter(msg):
  return set_onetime('util_butter', msg)

def get_butter():
  return get_onetime('util_butter')

def track_event(category, action, label, value=1):
  event = {
    'category': category,
    'action': action,
    'label': label,
    'value': value,
  }
  return set_onetime('util_track_event', event)

def get_track_event():
  return get_onetime('util_track_event')

def in_production():
  """Detects if app is running in production.

  Returns a boolean.
  """
  server_software = os.getenv('SERVER_SOFTWARE')
  if server_software is None:
    return False
  return not server_software.startswith('Development')
