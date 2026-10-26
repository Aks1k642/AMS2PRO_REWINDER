"""Generate launcher icons for Windows and Android (Pillow, no external graphics assets)."""
from pathlib import Path
from PIL import Image, ImageDraw
import math

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "branding"
BRAND.mkdir(exist_ok=True)
S = 1024
im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
# Rounded midnight-metal backdrop
d.rounded_rectangle((12, 12, 1012, 1012), radius=210, fill="#101b22", outline="#46616c", width=14)
d.rounded_rectangle((54, 54, 970, 970), radius=175, outline="#233944", width=7)
# Spool shadow, drum and filament
d.ellipse((203, 247, 845, 873), fill="#080d14")
d.rounded_rectangle((290, 264, 734, 816), radius=70, fill="#192e31", outline="#667e83", width=18)
d.rounded_rectangle((326, 321, 695, 764), radius=46, fill="#32e66e")
for x in range(350, 682, 22):
    d.line((x, 344, x, 744), fill="#0a7e4a", width=6)
d.ellipse((218, 252, 462, 830), fill="#293842", outline="#8ba1a7", width=19)
d.ellipse((297, 430, 391, 648), fill="#102128", outline="#8ba1a7", width=17)
d.ellipse((669, 252, 839, 830), fill="#24353c", outline="#8ba1a7", width=16)
# Circular rewinding arrow around spool, visible at small sizes
box=(143, 137, 879, 880)
d.arc(box, start=201, end=329, fill="#baffcb", width=40)
d.arc(box, start=336, end=428, fill="#baffcb", width=40)
angle=428*math.pi/180
cx=511; cy=508; radius=368
px=cx+radius*math.cos(angle); py=cy+radius*math.sin(angle)
# Tangential arrow tip points clockwise
dx=-math.sin(angle);dy=math.cos(angle)
tip=(px+68*dx,py+68*dy)
base=(px-38*dx,py-38*dy)
normal=(-dy,dx)
d.polygon([tip,(base[0]+49*normal[0],base[1]+49*normal[1]),(base[0]-49*normal[0],base[1]-49*normal[1])],fill="#baffcb")
# Output icon files
im=im.resize((512,512),Image.Resampling.LANCZOS)
im.save(BRAND/"app.png")
im.save(BRAND/"app.ico",sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
out=ROOT/"android-source/app/src/main/res/mipmap-xxxhdpi"
out.mkdir(parents=True,exist_ok=True)
im.resize((192,192),Image.Resampling.LANCZOS).save(out/"ic_launcher.png")
for folder,dim in [("mipmap-mdpi",48),("mipmap-hdpi",72),("mipmap-xhdpi",96),("mipmap-xxhdpi",144)]:
    path=ROOT/"android-source/app/src/main/res"/folder
    path.mkdir(parents=True,exist_ok=True)
    im.resize((dim,dim),Image.Resampling.LANCZOS).save(path/"ic_launcher.png")
print("Generated Windows ICO and Android launcher icons")
