#!/usr/bin/env python

import wsgiref.handlers

from google.appengine.api.labs import taskqueue
from google.appengine.ext import webapp
from google.appengine.api import users
from google.appengine.ext.webapp import template
from google.appengine.ext import db
from google.appengine.api import urlfetch
from google.appengine.api import mail
from google.appengine.api import xmpp
from google.appengine.ext.webapp.util import login_required
from datetime import datetime
import urllib, hashlib, time

def baseN(num,b,numerals="0123456789abcdefghijklmnopqrstuvwxyz"): 
    return ((num == 0) and  "0" ) or (baseN(num // b, b).lstrip("0") + numerals[num % b])

def broadcastRefresh(lobby):
    urlfetch.fetch('http://live.readyinrealtime.com/%s' % lobby.name, method='POST', payload=urllib.urlencode({'cmd': 'refresh'}))

class Lobby(db.Model):
    name = db.StringProperty(required=True)
    url = db.StringProperty(required=True)
    participants = db.IntegerProperty()
    created = db.DateTimeProperty(auto_now_add=True)
    updated = db.DateTimeProperty(auto_now=True)
    
    def __init__(self, *args, **kwargs):
        kwargs['name'] = kwargs.get('name', baseN(abs(hash(time.time())), 36))
        super(Lobby, self).__init__(*args, **kwargs)
    
    def ready(self):
        return (self.participants_ready() >= self.participants)
    
    def participants_ready(self):
        return self.participant_set.filter('ready =', True).count()

class Participant(db.Model):
    user = db.UserProperty(auto_current_user_add=True)
    lobby = db.ReferenceProperty(Lobby, required=True)
    ready = db.BooleanProperty(default=False)
    notify = db.BooleanProperty(default=True)
    created = db.DateTimeProperty(auto_now_add=True)
    updated = db.DateTimeProperty(auto_now=True)

class MainHandler(webapp.RequestHandler):
    def get(self):
        user = users.get_current_user()
        if user:
            logout_url = users.create_logout_url("/")
        else:
            login_url = users.create_login_url('/')
        self.response.out.write(template.render('templates/main.html', locals()))
    
    def post(self):
        url = self.request.get('url')
        if not url:
            self.redirect('/')
        else:
            participants = int(self.request.get('participants'))
            lobby = Lobby(url=url, participants=participants)
            lobby.put()
            self.redirect('/%s' % lobby.name)

class LobbyHandler(webapp.RequestHandler):
    @login_required
    def get(self):
        name = self.request.path.replace('/', '')
        lobby = Lobby.all().filter('name =', name).get()
        if lobby:
            if lobby.ready():
                self.redirect(lobby.url)
                return
            user = users.get_current_user()
            participant = Participant.all().filter('lobby =', lobby).filter('user =', user).get()
            if not participant:
                participant = Participant(lobby=lobby, user=user)
                participant.put()
                broadcastRefresh(lobby)
            logout_url = users.create_logout_url("/")
            host = self.request.host
            remaining_participants = range(lobby.participants - lobby.participant_set.count())
            self.response.out.write(template.render('templates/lobby.html', locals()))
        else:
            self.redirect('/')
            
    def post(self):
        name = self.request.path.replace('/', '')
        lobby = Lobby.all().filter('name =', name).get()
        if lobby:
            user = users.get_current_user()
            participant = Participant.all().filter('lobby =', lobby).filter('user =', user).get()
            if participant:
                participant.ready = True if self.request.get('ready') else False
                if participant.ready:
                    participant.notify = True if self.request.get('notify') else False
                    xmpp.send_invite(participant.user.email())
                participant.put()
                broadcastRefresh(lobby)
            if lobby.ready():
                xmpp.send_message([p.user.email() for p in lobby.participant_set if p.notify], "Ready! %s" % lobby.url)
        self.redirect('/%s' % name)

def main():
    application = webapp.WSGIApplication([
        ('/', MainHandler), 
        ('/.*', LobbyHandler),
        ], debug=True)
    wsgiref.handlers.CGIHandler().run(application)

if __name__ == '__main__':
    main()
