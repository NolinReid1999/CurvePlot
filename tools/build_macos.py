"""Build the existing Curve app/spec and its drag-to-Applications DMG."""
import subprocess,sys
from pathlib import Path
import dmgbuild

if sys.platform != 'darwin':
    raise SystemExit('DMG build requires macOS; this script does not build an EXE.')
repo=Path(__file__).resolve().parents[1]
subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--distpath',str(repo/'dist'),'--workpath',str(repo/'build'),'packaging/PhysicsPlot.spec'],cwd=repo,check=True)
app=repo/'dist/Curve.app'
for attr in ['com.apple.FinderInfo','com.apple.ResourceFork']:
    subprocess.run(['xattr','-drs',attr,str(app)],check=True)
subprocess.run(['codesign','--force','--deep','--sign','-',str(app)],check=True)
subprocess.run(['codesign','--verify','--deep','--strict',str(app)],check=True)
image=repo/'dist/Curve-1.0.0-build1-macOS-arm64.dmg'
if image.exists():
    raise SystemExit('Output already exists; move it aside before building another DMG.')
settings=dict(format='UDZO',compression_level=6,filesystem='HFS+',files=[str(app)],symlinks={'Applications':'/Applications'},background=str(repo/'packaging/dmg-background.png'),window_rect=((160,100),(700,560)),icon_locations={'Curve.app':(190,232),'Applications':(510,232)},icon_size=96,text_size=14,show_toolbar=False,show_sidebar=False,show_status_bar=False,show_pathbar=False,show_tab_view=False)
dmgbuild.build_dmg(str(image),'Curve 1.0.0 build1',settings=settings)
print(image)
