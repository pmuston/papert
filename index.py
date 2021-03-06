import os
import base64
import hashlib
import datetime

import jinja2
import webapp2

from google.appengine.ext import db
from google.appengine.api import images
from google.appengine.api import memcache

JINJA_ENV = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True)

def static_filter(filename, hashes={}):
    filename = 'static/%s' % filename
    if filename not in hashes:
        data = open(filename).read()
        hashes[filename] = hashlib.sha1(data).hexdigest()[:10]
    return '/%s?%s' % (filename, hashes[filename])

JINJA_ENV.filters['static'] = static_filter

class LogoProgram(db.Model):
    code = db.TextProperty()
    img  = db.BlobProperty()
    date = db.DateTimeProperty(auto_now_add=True)
    hash = db.StringProperty()

class Papert(webapp2.RequestHandler):
    def get(self):
        # block a terrible bot
        if 'ahref' in self.request.headers.get('User-Agent').lower():
            return

        hash = self.request.path[1:9] #this assumes that hashes are always 8 chars
        extra = self.request.path[9:]

        if extra == ".png" and hash == self.request.headers.get('If-None-Match'):
            self.response.set_status(304)
            return

        if extra not in ('', '.png'):
            self.redirect('/')
            return

        older = self.request.get("older")
        newer = self.request.get("newer")

        program = None

        if hash:
            program = memcache.get("program: %s" % hash)
            if program is None:
                program = LogoProgram.all().filter('hash = ', hash).get()
                if program is None:
                    memcache.set("program: %s" % hash, "not found")
                else:
                    memcache.set("program: %s" % hash, program)

            if program == "not found":
                program = None

            if program is None:
                self.redirect('/')

        if program and extra == ".png":
            # enable edge caching
            # https://code.google.com/p/googleappengine/issues/detail?id=2258#c14
            self.response.headers['Cache-Control'] = 'public, max-age:604800'
            self.response.headers['Pragma'] = 'Public'
            self.response.headers['Etag'] = str(program.hash)
            self.response.headers['Last-Modified'] = program.date.ctime()

            self.response.headers['Content-Type'] = 'image/png'
            self.response.out.write(program.img)
        else:
            values = {'code':""}
            if program:
                values['code'] = program.code
                values['hash'] = hash


            if older or newer:
                if older:
                    browse_date = datetime.datetime.strptime(older,"%Y-%m-%dT%H:%M:%S")
                    recent = LogoProgram.all().filter('date <', browse_date).order('-date').fetch(5)
                    values['older'] = older
                elif newer:
                    browse_date = datetime.datetime.strptime(newer,"%Y-%m-%dT%H:%M:%S")
                    recent = LogoProgram.all().filter('date >', browse_date).order('date').fetch(5)
                    recent.reverse()
                    values['newer'] = newer
                if recent:
                    values['recent'] = [program.hash for program in recent]
                    values['last_date'] = recent[-1].date.strftime("%Y-%m-%dT%H:%M:%S")
                    values['next_date'] = recent[0].date.strftime("%Y-%m-%dT%H:%M:%S")
            else:
                recent = memcache.get("recent_progs")
                last_date = memcache.get("last_prog_date")

                if not (recent and last_date):
                    recent = LogoProgram.all().order('-date').fetch(5)
                    if recent:
                        last_date = recent[-1].date.strftime("%Y-%m-%dT%H:%M:%S")
                        recent = [program.hash for program in recent]
                        memcache.set_multi({"recent_progs": recent,
                                            "last_prog_date": last_date}, time=3600)

                values['recent'] = recent
                values['last_date'] = last_date

            template = JINJA_ENV.get_template('index.html.tmpl')
            self.response.out.write(template.render(values))

    def post(self):
        code = self.request.get('code',None)
        img = self.request.get('img',"")

        # simple antispam
        if sum(x in code.lower() for x in ('href=', 'url=', 'link=')) > 2:
            self.redirect("/error")
            return

        if code.strip():
            hash = base64.b64encode(hashlib.sha1(code.strip()).digest()[:6], "-_")
            if not LogoProgram.all().filter('hash =', hash).get():
                program = LogoProgram()
                program.code = code
                program.hash = hash
                if img:
                    img = base64.b64decode(img)
                    img = images.Image(img)
                    img.resize(125, 125)
                    program.img = img.execute_transforms()
                else:
                    self.redirect("/error")
                    return
                program.put()
                memcache.set("program: %s" % hash, program)
                memcache.delete("recent_progs")
        else:
            hash = ""

        self.redirect("/%s" % hash)

app = webapp2.WSGIApplication([('/.*', Papert)])

if __name__ == "__main__":
    main()
