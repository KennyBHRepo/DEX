#!/usr/bin/env python3
"""Build STARK.app: a local native launcher around this project's existing Python runtime.
Run using the project's .venv/bin/python. The .app is local to this installation;
rebuild it after moving the project or replacing the Python installation.
"""
import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import sysconfig
import struct
import tempfile

NAME = 'STARK'
BUNDLE_ID = 'local.dex.app'
# macOS remembers privacy permissions (Accessibility, Camera) per code signature.
# A plain ad-hoc signature changes on every build, so a rebuilt app looks like a
# stranger and the old "On" switch silently stops applying. Pinning the
# designated requirement to the bundle identifier keeps the permission valid
# across rebuilds.
REQUIREMENT = f'=designated => identifier "{BUNDLE_ID}"'


def sign(bundle):
    base = ['codesign', '--force', '--sign', '-', '--identifier', BUNDLE_ID]
    try:
        subprocess.run(base + ['--requirements', REQUIREMENT, str(bundle)], check=True)
    except subprocess.CalledProcessError:
        print('Note: stable signing was refused; using a standard local signature.')
        subprocess.run(base + [str(bundle)], check=True)
    shown = subprocess.run(['codesign', '-d', '-r-', str(bundle)], capture_output=True, text=True)
    print('Signature requirement:', (shown.stdout or shown.stderr).strip().splitlines()[-1])

LAUNCHER = r'''
#import <Cocoa/Cocoa.h>
#include <dlfcn.h>
#include <wchar.h>
#include <stdio.h>
int main(int argc, char **argv) {
 @autoreleasepool {
    NSBundle *bundle = [NSBundle mainBundle];
    NSString *path = [bundle pathForResource:@"runtime" ofType:@"json"];
    NSDictionary *settings = [NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:path] options:0 error:nil];
    NSString *home = settings[@"home"], *library = settings[@"library"], *project = settings[@"project"], *packages = settings[@"packages"];
    NSString *script = [project stringByAppendingPathComponent:@"handcontrol.py"];
    if (!settings || ![[NSFileManager defaultManager] fileExistsAtPath:script] || ![[NSFileManager defaultManager] fileExistsAtPath:packages]) {
        [NSApplication sharedApplication];
        NSAlert *alert = [NSAlert new]; alert.messageText = @"STARK needs its HandControl folder";
        alert.informativeText = @"The HandControl folder or its Python environment has moved. Put it back on the Desktop, or run Install STARK.command from its new location.";
        [alert runModal]; return 1;
    }
    NSString *logs = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Logs/STARK"];
    [[NSFileManager defaultManager] createDirectoryAtPath:logs withIntermediateDirectories:YES attributes:nil error:nil];
    freopen([[logs stringByAppendingPathComponent:@"last-run.log"] fileSystemRepresentation],"w",stderr);
    dup2(fileno(stderr),fileno(stdout)); setbuf(stdout,NULL);
    void *python = dlopen([library fileSystemRepresentation],RTLD_NOW|RTLD_GLOBAL);
    if (!python) { fprintf(stderr,"Cannot load Python: %s\n",dlerror()); return 2; }
    wchar_t *(*decode)(const char*,size_t*) = dlsym(python,"Py_DecodeLocale");
    void (*setHome)(const wchar_t*) = dlsym(python,"Py_SetPythonHome");
    void (*setProgram)(const wchar_t*) = dlsym(python,"Py_SetProgramName");
    void (*initialize)(int) = dlsym(python,"Py_InitializeEx");
    int (*run)(const char*) = dlsym(python,"PyRun_SimpleString");
    if (!decode || !setHome || !setProgram || !initialize || !run) return 3;
    setHome(decode([home fileSystemRepresentation],NULL));
    setProgram(decode([[bundle executablePath] fileSystemRepresentation],NULL));
    initialize(0);
    NSData *encoded = [NSJSONSerialization dataWithJSONObject:@[project,packages] options:0 error:nil];
    NSString *payload = [encoded base64EncodedStringWithOptions:0];
    NSString *code = [NSString stringWithFormat:@"import sys, os, json, base64\np, s = json.loads(base64.b64decode('%@'))\nsys.path[:0] = [p, s]\nos.chdir(p)\nsys.argv = [os.path.join(p, 'handcontrol.py')]\nimport handcontrol\nhandcontrol.main()\n",payload];
    int result = run([code UTF8String]);
    if (result) {
        [NSApplication sharedApplication];NSAlert *alert=[NSAlert new];alert.messageText=@"STARK couldn’t finish starting";
        alert.informativeText=@"Details are in Library/Logs/STARK/last-run.log. Your settings are unchanged.";[alert runModal];
    }
    return result ? 1 : 0;
 }
}
'''

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('--output',type=Path,default=Path.home()/'Desktop'/'STARK.app')
    args=parser.parse_args()
    project=args.project.resolve(); bundle=args.output.resolve()
    macos=bundle/'Contents/MacOS'; resources=bundle/'Contents/Resources'
    macos.mkdir(parents=True,exist_ok=True);resources.mkdir(parents=True,exist_ok=True)
    home=Path(sys.base_prefix)
    candidates=[home/'Python3',home/'Python',home/'lib'/str(sysconfig.get_config_var('LDLIBRARY'))]
    library=next((p for p in candidates if p.is_file()),None)
    if library is None:raise RuntimeError('Cannot find the shared Python runtime.')
    packages=Path(sysconfig.get_paths()['purelib'])
    runtime=dict(home=str(home),library=str(library),project=str(project),packages=str(packages))
    (resources/'runtime.json').write_text(json.dumps(runtime))
    info=dict(CFBundleName=NAME,CFBundleDisplayName=NAME,CFBundleIdentifier=BUNDLE_ID,
        CFBundleExecutable=NAME,CFBundlePackageType='APPL',CFBundleVersion='4',CFBundleShortVersionString='1.1.0',
        CFBundleIconFile=NAME,NSHighResolutionCapable=True,LSMinimumSystemVersion='12.0',
        NSMicrophoneUsageDescription='Optional double-clap wake detects two claps while STARK is standing by. Audio stays on this Mac and is never saved.',
        NSCameraUsageDescription='STARK uses the camera to see your hand gestures. Video stays on this Mac and is never recorded.')
    with (bundle/'Contents/Info.plist').open('wb') as f:plistlib.dump(info,f)
    icon=project/'assets/stark-icon.png'
    with tempfile.TemporaryDirectory() as temp:
        temp=Path(temp); source=temp/'launcher.m';source.write_text(LAUNCHER)
        subprocess.run(['clang','-fobjc-arc','-framework','Cocoa',str(source),'-o',str(macos/NAME)],check=True)
        iconset=temp/'STARK.iconset';iconset.mkdir()
        for size in (16,32,128,256,512):
            for scale in (1,2):
                name=f'icon_{size}x{size}'+('@2x' if scale==2 else '')+'.png'
                subprocess.run(['sips','-z',str(size*scale),str(size*scale),str(icon),'--out',str(iconset/name)],check=True,stdout=subprocess.DEVNULL)
        # Pack the standard PNG representations directly (also works headlessly).
        chunks=[]
        for name,tag in [('icon_16x16.png',b'icp4'),('icon_32x32.png',b'icp5'),('icon_32x32@2x.png',b'icp6'),('icon_128x128.png',b'ic07'),('icon_256x256.png',b'ic08'),('icon_512x512.png',b'ic09'),('icon_512x512@2x.png',b'ic10')]:
            data=(iconset/name).read_bytes()
            chunks.append(tag+struct.pack('>I',len(data)+8)+data)
        payload=b''.join(chunks)
        (resources/(NAME+'.icns')).write_bytes(b'icns'+struct.pack('>I',len(payload)+8)+payload)
    subprocess.run(['clang','-dynamiclib','-fobjc-arc','-framework','AVFoundation',
                    '-framework','Foundation',str(project/'clap_audio.m'),
                    '-o',str(resources/'libDexAudio.dylib')],check=True)
    subprocess.run(['codesign','--force','--sign','-',str(resources/'libDexAudio.dylib')],check=True)
    sign(bundle)
    print(f'Built {bundle}\nUses project: {project}\nUses Python packages: {packages}')

if __name__=='__main__':main()
