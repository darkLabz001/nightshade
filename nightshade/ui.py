from datetime import datetime
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont

# High-contrast palette. The first revision used near-black greys (#34263f
# lines, #94849f text) on a #09080e background, which on this small ST7789
# panel reads as an almost blank black screen with a couple of faint lines.
# These values keep the dark theme but push every element well clear of black.
BG = '#000000'; PANEL = '#1b1230'; LINE = '#a98cc2'; MUTED = '#cdbcdd'
WHITE = '#ffffff'; VIOLET = '#cfa8ff'; RED = '#ff6b8a'
MENU = [('System', 'Vitals in the dark'), ('Network', 'Follow the signal'),
        ('Scripts', 'Choose your ritual'), ('Settings', 'Make it yours')]
# Friendly titles for sections that config.json leaves implicit (a script with
# a "section" but no matching entry under "sections").
SECTION_NAMES = {'wifi': 'Wi-Fi', 'wlan': 'Wi-Fi', 'ble': 'Bluetooth',
                 'bluetooth': 'Bluetooth', 'bt': 'Bluetooth', 'net': 'Network',
                 'network': 'Network'}

@lru_cache(maxsize=32)
def font(size, bold=False, serif=False):
    family = 'DejaVuSerif' if serif else 'DejaVuSans'
    name = family + ('-Bold' if bold else '') + '.ttf'
    try: return ImageFont.truetype('/usr/share/fonts/truetype/dejavu/'+name,size)
    except OSError: return ImageFont.load_default(size=size)


def clipped(draw, xy, text, width, size=12, fill=WHITE, bold=False):
    text = str(text); f = font(size,bold)
    while text and draw.textlength(text,font=f)>width:
        text=text[:-2]+'…' if len(text)>2 else ''
    draw.text(xy,text,font=f,fill=fill)


def sigil(d,x,y,size=22):
    d.ellipse((x-size,y-size,x+size,y+size),outline=VIOLET,width=2)
    d.ellipse((x-size+10,y-size-4,x+size+7,y+size-8),fill=BG)
    d.line((x+15,y+9,x+15,y+29),fill=RED,width=2)
    d.line((x+9,y+16,x+21,y+16),fill=RED,width=2)
    d.polygon([(x-27,y-13),(x-23,y-17),(x-19,y-13),(x-23,y-9)],fill=MUTED)


class Model:
    def __init__(self,scripts,sections=None):
        self.scripts=list(scripts); self.page='home'; self.index=0; self.scroll=0
        self.last_key='—'; self.notice=''; self.asleep=False; self.section_index=0
        self.sections=self._build_sections(sections)
        self.by_section={section['id']:[] for section in self.sections}
        for script in self.scripts:
            sid=script.get('section') or self.sections[0]['id']
            if sid not in self.by_section:
                # A script naming a section that is not in the config: register
                # it on the fly so its tools are still reachable.
                self.sections.append({'id':sid,'name':SECTION_NAMES.get(sid,sid.title()),'description':''})
                self.by_section[sid]=[]
            self.by_section[sid].append(script)

    def _build_sections(self,sections):
        if sections:
            return [dict(section) for section in sections]
        ordered=[];seen=set()
        for script in self.scripts:
            sid=script.get('section') or 'general'
            if sid not in seen:
                seen.add(sid)
                ordered.append({'id':sid,'name':SECTION_NAMES.get(sid,sid.title()),'description':''})
        return ordered or [{'id':'general','name':'General','description':''}]

    @property
    def section(self):
        return self.sections[self.section_index] if self.sections else None

    def visible_scripts(self):
        return self.by_section.get(self.section['id'],[]) if self.section else []

    def enter_scripts(self):
        self.index=0;self.scroll=0
        self.page='sections' if len(self.sections)>1 else 'scripts'

    def _back(self):
        if self.page=='sections':
            self.page='home';self.index=2
        elif self.page=='scripts':
            if len(self.sections)>1:self.page='sections'
            else:self.page='home';self.index=2
        elif self.page in ('confirm','output'):
            self.page='scripts'
        elif self.page=='settings':
            self.page='home';self.index=3
        elif self.page in ('controls','colors'):
            self.page='settings'
        else:
            self.page='home'

    def key(self,key,runner):
        self.last_key=key
        if self.asleep: self.asleep=False; return None
        if key=='KEY3': runner.stop(); self.notice='Stop requested'; return None
        if key=='KEY2': self.page='home';self.index=0;self.section_index=0;self.scroll=0;return None
        if key in ('LEFT','KEY1'): self._back(); return None
        if self.page=='home':
            if key in ('UP','DOWN'): self.index=(self.index+(1 if key=='DOWN' else -1))%len(MENU)
            elif key in ('OK','RIGHT'):
                page=MENU[self.index][0].lower()
                if page=='scripts': self.enter_scripts()
                else: self.page=page;self.index=0;self.scroll=0
        elif self.page=='sections':
            if key in ('UP','DOWN'): self.section_index=(self.section_index+(1 if key=='DOWN' else -1))%len(self.sections)
            elif key in ('OK','RIGHT'): self.index=0;self.page='scripts'
        elif self.page=='scripts':
            current=self.visible_scripts()
            if current:
                if key in ('UP','DOWN'): self.index=(self.index+(1 if key=='DOWN' else -1))%len(current)
                elif key in ('OK','RIGHT'): self.page='confirm'
        elif self.page=='confirm' and key in ('OK','RIGHT'):
            script=self.visible_scripts()[self.index]
            if runner.start(script['id']):self.page='output';self.scroll=0
            else:self.notice='Job busy or failed';self.page='output'
        elif self.page=='output':
            if key=='UP':self.scroll=min(140,self.scroll+1)
            elif key=='DOWN':self.scroll=max(0,self.scroll-1)
        elif self.page=='settings':
            if key in ('UP','DOWN'): self.index=(self.index+(1 if key=='DOWN' else -1))%5
            elif key in ('OK','RIGHT'):
                if self.index==0:return 'rotate'
                if self.index==1:self.asleep=True
                if self.index==2:self.page='controls'
                if self.index==3:self.page='colors'
                if self.index==4:
                    # OTA update: runs like any other tool, so the
                    # output page doubles as the progress screen and
                    # KEY3 can still stop it.
                    if runner.start('ota-update'):
                        self.page='output';self.scroll=0
                    else:
                        self.notice='Job busy or failed';self.page='output'
        elif self.page in ('network','system') and key in ('UP','DOWN'):
            self.scroll=max(0,min(8,self.scroll+(1 if key=='DOWN' else -1)))
        return None


    def render(self,stats,job,hardware,rotation):
        img=Image.new('RGB',(240,240),BG);d=ImageDraw.Draw(img)
        if self.asleep:return img
        d.rectangle((0,0,239,5),fill=VIOLET)
        d.text((12,10),'N / S',font=font(13,True),fill=VIOLET)
        d.text((228,10),datetime.now().strftime('%H:%M'),font=font(13),fill=MUTED,anchor='ra')
        d.line((12,32,228,32),fill=LINE,width=2)
        if self.page=='home':
            d.text((11,38),'Nightshade',font=font(28,True,True),fill=WHITE)
            d.text((13,76),'AFTER HOURS / ALWAYS AWAKE',font=font(11),fill=MUTED)
            sigil(d,208,60,15)
            for i,(title,subtitle) in enumerate(MENU):
                y=92+i*30;active=i==self.index
                if active:
                    d.rounded_rectangle((8,y,231,y+28),radius=5,fill='#2a1840',outline=VIOLET,width=2)
                    d.rectangle((10,y+5,13,y+23),fill=RED)
                d.text((20,y+7),f'0{i+1}',font=font(12,True),fill=RED if active else MUTED)
                d.text((48,y+4),title,font=font(17,active),fill=WHITE if active else MUTED)
                if active:d.text((224,y+3),'\u203a',font=font(20,True),fill=VIOLET,anchor='ra')
        else:
            title={'confirm':'Run ritual?','output':'Script output','controls':'Control check','sections':'Sections'}.get(self.page)
            if title is None:title=self.section['name'] if self.page=='scripts' and len(self.sections)>1 and self.section else self.page.title()
            d.text((11,38),title,font=font(24,True,True),fill=WHITE)
            if self.page=='system':
                temp=stats.get('temperature')
                rows=[('HOST',stats.get('hostname','—')),('CPU',f"{stats.get('cpu',0)}%"),
                    ('MEMORY',f"{stats.get('memory',0)}%"),('TEMP',f'{temp}°C' if temp else '—'),
                    ('UPTIME',stats.get('uptime','—')),('DISK',f"{stats.get('disk',0)}%")]
                self.rows(d,rows,self.scroll)
            elif self.page=='network':
                rows=[('TAILSCALE',stats.get('tailscale','—')),('TAIL IP',stats.get('tail_ip','—')),
                      ('WI-FI',stats.get('ssid','—')),('GATEWAY',stats.get('gateway','—'))]
                rows += [(a['interface'],a['ip']) for a in stats.get('addresses',[])]
                self.rows(d,rows,self.scroll)
            elif self.page=='sections':
                start=max(0,self.section_index-3)
                for n,section in enumerate(self.sections[start:start+4],start):
                    y=78+(n-start)*34
                    if n==self.section_index:d.rounded_rectangle((8,y,231,y+31),radius=5,fill='#2a1840',outline=VIOLET,width=2)
                    clipped(d,(18,y+7),section['name'],168,16,WHITE if n==self.section_index else MUTED)
                    count=len(self.by_section.get(section['id'],[]))
                    d.text((224,y+8),str(count),font=font(13,True),fill=VIOLET,anchor='ra')
            elif self.page=='scripts':
                current=self.visible_scripts();start=max(0,self.index-3)
                for n,script in enumerate(current[start:start+4],start):
                    y=78+(n-start)*34
                    if n==self.index:d.rounded_rectangle((8,y,231,y+31),radius=5,fill='#2a1840',outline=VIOLET,width=2)
                    clipped(d,(18,y+7),script['name'],204,15,WHITE if n==self.index else MUTED)
                if not current:clipped(d,(14,90),'No tools here',210)
            elif self.page=='confirm':
                script=self.visible_scripts()[self.index]
                clipped(d,(14,80),script['name'],210,18,VIOLET,True)
                import textwrap
                for i,line in enumerate(textwrap.wrap(script.get('description',''),27)[:4]):
                    d.text((14,114+i*19),line,font=font(12),fill=MUTED)
                d.text((14,192),'PRESS CENTER TO RUN',font=font(12,True),fill=RED)
            elif self.page=='output':
                clipped(d,(14,72),job['name']+' / '+job['status'],210,11,VIOLET)
                import textwrap
                lines=[part for line in job['lines'] for part in (textwrap.wrap(line,28) or [''])]
                end=max(0,len(lines)-self.scroll)
                for i,line in enumerate(lines[max(0,end-6):end]):
                    clipped(d,(14,94+i*19),line,212,12)
                if not lines:d.text((14,104),'Waiting for output…',font=font(13),fill=MUTED)
            elif self.page=='settings':
                rows=[f'Rotate screen / {rotation}°','Sleep screen',
                      'Test buttons','Test colors','Update from GitHub']
                for i,line in enumerate(rows):
                    y=78+i*28
                    if self.index==i:d.rounded_rectangle((8,y,231,y+26),radius=5,fill='#2a1840',outline=VIOLET,width=2)
                    clipped(d,(18,y+6),line,204,15)
            elif self.page=='controls':
                d.text((14,84),'LAST INPUT',font=font(11),fill=MUTED)
                d.text((14,104),self.last_key,font=font(30,True),fill=VIOLET)
                d.text((14,160),'Move joystick / press buttons',font=font(12),fill=MUTED)
                d.text((14,182),'KEY2 returns home',font=font(12),fill=RED)
            elif self.page=='colors':
                d.text((14,74),'IS THIS DISPLAY RECEIVING RGB?',font=font(10),fill=MUTED)
                colors=[('#ff0000','RED'),('#00ff00','GREEN'),('#0000ff','BLUE'),
                        ('#00ffff','CYAN'),('#ff00ff','MAGENTA'),('#ffff00','YELLOW'),
                        ('#ffffff','WHITE'),('#000000','BLACK')]
                for i,(color,label) in enumerate(colors):
                    x=14+(i%2)*109;y=92+(i//2)*28
                    d.rounded_rectangle((x,y,x+52,y+20),radius=3,fill=color,outline='#ffffff')
                    clipped(d,(x+58,y+4),label,49,10,MUTED)
                d.text((14,208),'PRESS ANY KEY / RETURN TO MENU',font=font(10,True),fill=RED)
        d.line((12,220,228,220),fill=LINE,width=2)
        d.text((12,226),'1 BACK   2 HOME   3 STOP',font=font(11),fill=MUTED)
        d.ellipse((222,226,232,236),fill=VIOLET if hardware else RED)
        return img

    @staticmethod
    def rows(d,rows,scroll):
        start=min(scroll,max(0,len(rows)-5))
        for i,(label,value) in enumerate(rows[start:start+5]):
            y=80+i*28
            d.text((14,y),label.upper(),font=font(10,True),fill=MUTED)
            clipped(d,(96,y-3),value,134,14)
