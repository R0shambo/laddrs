import logging
import os

os.environ['DJANGO_SETTINGS_MODULE'] = 'settings'
from google.appengine.dist import use_library
try:
  use_library('django', '1.2')
except Exception, e:
  logging.exception("Fatal exception. Will try to force an instance restart.")
  raise SystemExit(1)


def webapp_add_wsgi_middleware(app):
  from google.appengine.ext.appstats import recording
  app = recording.appstats_wsgi_middleware(app)
  return app
