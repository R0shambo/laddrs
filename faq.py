import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'settings'

from google.appengine.dist import use_library
use_library('django', '1.2')

import cgi
import datetime
import urllib
import wsgiref.handlers
import pprint

from google.appengine.api import mail
from google.appengine.ext.webapp import template
from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp.util import run_wsgi_app

from laddrslib import util

SUPPORT_EMAIL="sc2.laddrs@gmail.com"

class MainPage(webapp.RequestHandler):
  def get(self):
    template_values = util.add_user_tmplvars(self, {})
    path = os.path.join(os.path.dirname(__file__), 'tmpl/faq.html')
    self.response.out.write(template.render(path, template_values))

  def post(self):
    if not util.csrf_protect(self):
      self.redirect(users.create_login_url(self.request.uri))
      return

    user = users.get_current_user()
    category = self.request.get('category')
    summary = self.request.get('summary')
    message = self.request.get('message')
    attachment = self.request.get('attachment')

    if not category:
      errormsg = "Category required."
    elif not summary:
      errormsg = "Summary required."
    elif not message:
      errormsg = "Message required."
    elif category == 'REPLAY' and not attachment:
      errormsg = "Please attach the replay file with your message."
    else:
      message = mail.EmailMessage(
        sender=user.email(),
        to=SUPPORT_EMAIL,
        subject="%s: %s" % (category, summary),
        body=message)
      if attachment:
        message.attachments = [(self.request.POST["attachment"].filename,
                                attachment)]
      message.send()
      util.set_butter("Message sent to Support.")
      self.redirect("/faq")
      return

    template_values = util.add_user_tmplvars(self, {
      'errormsg': errormsg,
      'category': category,
      'summary': summary,
      'message': message,
    })
    path = os.path.join(os.path.dirname(__file__), 'tmpl/faq.html')
    self.response.out.write(template.render(path, template_values))


application = webapp.WSGIApplication([
  ('/faq', MainPage),
], debug=True)


def main():
  run_wsgi_app(application)


if __name__ == '__main__':
  main()
