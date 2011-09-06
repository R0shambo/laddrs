from google.appengine.api import users

def add_user_tmplvars(handler, tmplvars):
  user = users.get_current_user()
  tmplvars['user'] = user
  if user:
    tmplvars['auth_url'] = users.create_logout_url(handler.request.uri)
    tmplvars['auth_url_linktext'] = 'Logout %s' % user.nickname()
  else:
    tmplvars['auth_url'] = users.create_login_url(handler.request.uri)
    tmplvars['auth_url_linktext'] = 'Login'

  return tmplvars

def ordinal(value):
  """
  Converts zero or a *postive* integer (or their string 
  representations) to an ordinal value.

  >>> for i in range(1,13):
  ...     ordinal(i)
  ...     
  u'1st'
  u'2nd'
  u'3rd'
  u'4th'
  u'5th'
  u'6th'
  u'7th'
  u'8th'
  u'9th'
  u'10th'
  u'11th'
  u'12th'

  >>> for i in (100, '111', '112',1011):
  ...     ordinal(i)
  ...     
  u'100th'
  u'111th'
  u'112th'
  u'1011th'

  """
  try:
    value = int(value)
  except ValueError:
    return value

  if value % 100//10 != 1:
    if value % 10 == 1:
      ordval = u"%d%s" % (value, "st")
    elif value % 10 == 2:
      ordval = u"%d%s" % (value, "nd")
    elif value % 10 == 3:
      ordval = u"%d%s" % (value, "rd")
    else:
      ordval = u"%d%s" % (value, "th")
  else:
    ordval = u"%d%s" % (value, "th")

  return ordval
