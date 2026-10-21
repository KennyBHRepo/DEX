"""STARK: the native macOS home for the HandControl gesture engine."""
import os
import queue
import subprocess
import time
import AppKit as A
import Foundation as F
import Quartz
import AVFoundation as AV
import objc
from gestures import DEFAULTS, DEFAULT_BINDINGS
from preferences import FIELDS, validate_settings, save_settings
from runtime import CaptureWorker
from session import Lesson, STEPS
from shortcuts import GlobalShortcut
import controls as C

HERE = os.path.dirname(os.path.abspath(__file__))
ICON = os.path.join(HERE, 'assets', 'stark-icon.png')
BUNDLE_ID = 'local.dex.app'
ACCENT_RGB = (.08, .36, .53)
ACCENT = A.NSColor.colorWithSRGBRed_green_blue_alpha_(.34, .82, .95, 1)
BACKGROUND = A.NSColor.colorWithSRGBRed_green_blue_alpha_(.035, .048, .078, 1)
SURFACE = A.NSColor.colorWithSRGBRed_green_blue_alpha_(.065, .080, .12, 1)
PRIVACY = 'x-apple.systempreferences:com.apple.preference.security?'


def ax_trusted(prompt=False):
    """True when macOS lets STARK post mouse and keyboard events."""
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
        return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: bool(prompt)}))
    except Exception:
        return False


def label(parent, text, x, y, width, height=24, size=14, bold=False, muted=False):
    view = A.NSTextField.alloc().initWithFrame_(((x, y), (width, height)))
    view.setStringValue_(text)
    view.setEditable_(False)
    view.setSelectable_(False)
    view.setBezeled_(False)
    view.setDrawsBackground_(False)
    view.setFont_((A.NSFont.boldSystemFontOfSize_ if bold else A.NSFont.systemFontOfSize_)(size))
    view.setTextColor_(A.NSColor.secondaryLabelColor() if muted else A.NSColor.labelColor())
    view.setLineBreakMode_(A.NSLineBreakByWordWrapping)
    parent.addSubview_(view)
    return view


def button(parent, title, x, y, width, target, action, primary=False, height=38):
    b = A.NSButton.alloc().initWithFrame_(((x, y), (width, height)))
    b.setTitle_(title)
    b.setBezelStyle_(A.NSBezelStyleRounded)
    b.setFont_(A.NSFont.systemFontOfSize_(14))
    b.setTarget_(target)
    b.setAction_(action)
    if primary:
        b.setBordered_(False)
        b.setWantsLayer_(True)
        b.layer().setCornerRadius_(11)
        b.layer().setBackgroundColor_(Quartz.CGColorCreateGenericRGB(*ACCENT_RGB, 1))
        b.setContentTintColor_(A.NSColor.whiteColor())
        paint_primary(b)
    parent.addSubview_(b)
    return b


def paint_primary(b):
    b.setAttributedTitle_(F.NSAttributedString.alloc().initWithString_attributes_(
        b.title(), {A.NSForegroundColorAttributeName: A.NSColor.whiteColor(),
                    A.NSFontAttributeName: A.NSFont.boldSystemFontOfSize_(14)}))


def image_view(parent, image, x, y, w, h):
    view = A.NSImageView.alloc().initWithFrame_(((x, y), (w, h)))
    view.setImageScaling_(A.NSImageScaleProportionallyUpOrDown)
    view.setImage_(image)
    parent.addSubview_(view)
    return view


def card(parent, x, y, w, h):
    view = A.NSBox.alloc().initWithFrame_(((x, y), (w, h)))
    view.setBoxType_(A.NSBoxCustom)
    view.setBorderType_(A.NSLineBorder)
    view.setBorderWidth_(1)
    view.setBorderColor_(A.NSColor.colorWithSRGBRed_green_blue_alpha_(.24, .22, .36, 1))
    view.setCornerRadius_(20)
    view.setFillColor_(SURFACE)
    view.setContentViewMargins_((0, 0))
    parent.addSubview_(view)
    return view.contentView()


class FlippedView(A.NSView):
    """Top-down layout for the scrolling Controls list."""

    def isFlipped(self):
        return True


class Desktop(A.NSObject):
    def applicationDidFinishLaunching_(self, notification):
        A.NSApp.setAppearance_(A.NSAppearance.appearanceNamed_(A.NSAppearanceNameDarkAqua))
        self.test_mode = getattr(self, 'test_mode', False)
        self.closing = False
        self.compact = None
        self.clap_listener = None
        self.clap_failed = False
        self.mic_pending = False
        self.mic_message = 'Double-clap wake off' 
        self.mode = 'off'
        self.requested_mode = 'off'
        self.ready = False
        self.busy = False
        self.fatal = False
        self.error = ''
        self.settings = None
        self.controls = None
        self.monitor = None
        self.recorder = None
        self.recording_key = None
        self.awaiting_access = False
        self.access_since = self.access_checked = 0.0
        self.access_hint = False
        self.config = dict(DEFAULTS, gesture_guard=True, clap_wake=False)
        self.bindings = dict(DEFAULT_BINDINGS)
        self.camera_names = []
        self.camera_index = 0
        self.lesson = Lesson()
        import handcontrol as hc
        self.config_path = getattr(self, 'config_path', None) or hc.CONFIG
        seen = F.NSUserDefaults.standardUserDefaults().boolForKey_('DexHasSeenWelcome')
        self.onboarding = (not seen or self.args.dry_run) and not self.test_mode
        self.worker = CaptureWorker(self.args)
        self.window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((80, 70), (1040, 710)),
            A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable | A.NSWindowStyleMaskMiniaturizable,
            A.NSBackingStoreBuffered, False)
        self.window.setTitle_('STARK')
        self.window.setDelegate_(self)
        self.window.setReleasedWhenClosed_(False)
        self.window.setBackgroundColor_(BACKGROUND)
        root = self.window.contentView()
        self.icon = A.NSImage.alloc().initWithContentsOfFile_(ICON)
        if self.icon and not self.test_mode:
            A.NSApp.setApplicationIconImage_(self.icon)
        image_view(root, self.icon, 24, 634, 52, 52)
        label(root, 'STARK', 85, 649, 400, 34, 27, True)
        label(root, 'Spatial Tracking and Recognition Kit', 87, 626, 440, 25, 13, muted=True)
        button(root, 'Mini preview', 650, 641, 130, self, 'showCompact:')
        self.controls_button = button(root, 'Controls…', 790, 641, 112, self, 'openControls:')
        self.settings_button = button(root, 'Settings…', 910, 641, 107, self, 'openSettings:')
        self.camera_card = card(root, 24, 110, 660, 494)
        self.preview = image_view(self.camera_card, None, 0, 0, 660, 494)
        self.preview.setWantsLayer_(True)
        self.preview.layer().setCornerRadius_(20)
        self.preview.layer().setMasksToBounds_(True)
        self.rest_icon = image_view(self.camera_card, self.icon, 262, 255, 136, 136)
        self.rest_title = label(self.camera_card, 'Standing by.', 55, 182, 550, 42, 29, True)
        self.rest_title.setAlignment_(A.NSTextAlignmentCenter)
        self.rest_copy = label(self.camera_card, 'Camera off. Move freely.', 45, 92, 570, 88, 16, muted=True)
        self.rest_copy.setAlignment_(A.NSTextAlignmentCenter)
        self.camera_note = label(root, 'Camera off · nothing is being recognized', 28, 78, 650, 25, 13, muted=True)
        self.feedback = label(root, 'Ready when you are.', 28, 36, 650, 29, 18, True)
        self.mic_note = label(root, 'Double-clap wake off', 28, 9, 650, 22, 11, muted=True)
        self.side = card(root, 706, 110, 310, 494)
        self.eyebrow = label(self.side, 'YOUR HANDS, YOUR CALL', 24, 450, 266, 23, 11, True, True)
        self.heading = label(self.side, 'Gestures are off', 24, 371, 266, 72, 27, True)
        self.description = label(self.side, '', 24, 258, 266, 112, 16, muted=True)
        self.success = label(self.side, '', 24, 194, 266, 57, 14, True)
        self.success.setTextColor_(ACCENT)
        self.primary = button(self.side, 'Turn gestures on', 19, 135, 272, self, 'primaryAction:', True, 46)
        self.secondary = button(self.side, 'Show me how', 19, 84, 272, self, 'secondaryAction:')
        self.back_button = button(self.side, 'Back', 19, 31, 88, self, 'previousLesson:')
        self.skip_button = button(self.side, 'Skip this step', 114, 31, 177, self, 'skipLesson:')
        self.shortcut_note = label(root, 'Also in your menu bar', 714, 68, 290, 40, 12, muted=True)
        self.privacy_button = button(root, 'Open Settings…', 704, 25, 150, self, 'openPrivacy:')
        self.fix_button = button(root, 'Fix permission…', 862, 25, 156, self, 'fixPermission:')
        self.privacy_button.setHidden_(True)
        self.fix_button.setHidden_(True)
        self.makeMenus()
        self.hotkey = None
        if not self.test_mode:
            try:
                self.hotkey = GlobalShortcut(lambda: self.toggleGestures_(None))
            except Exception:
                self.hotkey = None
        if self.hotkey and self.hotkey.available:
            self.shortcut_note.setStringValue_('⌃⌥M turns gestures on or off\nfrom any app. Or use the menu bar.')
        self.renderPanel()
        self.window.center()
        if not self.test_mode:
            self.window.makeKeyAndOrderFront_(None)
            A.NSApp.activateIgnoringOtherApps_(True)
            self.worker.start()
            self.timer = F.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                .04, self, 'refresh:', None, True)

    # ------------------------------------------------------------ menus
    @objc.python_method
    def makeMenus(self):
        main = A.NSMenu.alloc().init()
        head = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('STARK', None, '')
        appmenu = A.NSMenu.alloc().initWithTitle_('STARK')
        for title, action, key in [('About STARK', 'about:', ''), ('Controls…', 'openControls:', 'k'),
                                   ('Settings…', 'openSettings:', ','), ('Quit STARK', 'terminate:', 'q')]:
            item = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key)
            if action != 'terminate:':
                item.setTarget_(self)
            appmenu.addItem_(item)
        head.setSubmenu_(appmenu)
        main.addItem_(head)
        edithead = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_('Edit', None, '')
        edit = A.NSMenu.alloc().initWithTitle_('Edit')
        for title, action, key in [('Cut', 'cut:', 'x'), ('Copy', 'copy:', 'c'),
                                   ('Paste', 'paste:', 'v'), ('Select All', 'selectAll:', 'a')]:
            edit.addItem_(A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, key))
        edithead.setSubmenu_(edit)
        main.addItem_(edithead)
        if not self.test_mode:
            A.NSApp.setMainMenu_(main)
        self.status_item = A.NSStatusBar.systemStatusBar().statusItemWithLength_(A.NSVariableStatusItemLength)
        self.status_item.button().setTitle_('STARK ○')
        self.status_item.button().setToolTip_('STARK: gestures off')
        menu = A.NSMenu.alloc().init()
        self.menu_toggle = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            'Turn gestures on', 'toggleGestures:', '')
        self.menu_toggle.setTarget_(self)
        menu.addItem_(self.menu_toggle)
        menu.addItem_(A.NSMenuItem.separatorItem())
        for title, action in [('Show STARK', 'showWindow:'), ('Mini preview', 'showCompact:'), ('Learn the basics…', 'startLesson:'),
                              ('Controls…', 'openControls:'), ('Settings…', 'openSettings:'),
                              ('Quit STARK', 'terminate:')]:
            item = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, '')
            if action != 'terminate:':
                item.setTarget_(self)
            menu.addItem_(item)
        self.status_item.setMenu_(menu)

    # ------------------------------------------------------------ main panel
    @objc.python_method
    def editing(self):
        return self.settings is not None or self.controls is not None

    @objc.python_method
    def renderPanel(self):
        self.back_button.setHidden_(not self.onboarding)
        self.skip_button.setHidden_(not self.onboarding)
        if self.awaiting_access and not self.onboarding:
            self.eyebrow.setStringValue_('ONE-TIME SETUP')
            self.heading.setStringValue_('Allow pointer control')
            self.description.setStringValue_('macOS asks once before any app can move the pointer. '
                                             'Turn on STARK in Accessibility.')
            self.success.setStringValue_('STARK continues by itself.')
            self.primary.setTitle_('Open Accessibility')
            self.primary.setEnabled_(True)
            self.secondary.setTitle_('Cancel')
        elif self.onboarding:
            step = self.lesson.step
            title, body, cta, _ = STEPS[step]
            role = 'left' if self.config.get('swap_hands') else 'right'
            if step in (1, 2):
                body = body.replace('your pointer hand', f'your {role} hand')
            if step == 3:
                body = f'With your {role} hand, ' + body[0].lower() + body[1:]
            if step == 4:
                body = body.replace('your other hand', f'your {"right" if role == "left" else "left"} hand')
            self.eyebrow.setStringValue_('QUICK START' if step == 0 else 'YOU’RE SET' if step == 6
                                         else f'LEARN BY DOING · {step} OF 5')
            self.heading.setStringValue_(title)
            self.description.setStringValue_(body)
            self.primary.setTitle_(cta)
            self.secondary.setTitle_('Maybe later' if step == 0 else 'Try that again' if step == 6
                                     else 'Finish for now')
            self.back_button.setEnabled_(step > 0)
            self.skip_button.setHidden_(step in (0, 6))
            success = ['', 'Got you.', 'Tracking locked.', 'That’s a click.', 'That’s a scroll.',
                       'Off means off.'][step] if step < 6 else ''
            self.success.setStringValue_(success if self.lesson.complete else (
                'Safe practice · your Mac won’t react' if 1 <= step <= 5
                else 'Turn gestures on whenever you’re ready.' if step == 6 else 'About a minute.'))
            self.primary.setEnabled_(self.ready and not self.busy and not self.fatal)
        else:
            active = self.mode != 'off' or self.requested_mode != 'off'
            self.eyebrow.setStringValue_('YOUR HANDS, YOUR CALL')
            self.heading.setStringValue_('Just practicing' if self.mode == 'practice'
                                         else 'Gestures are on' if active else 'Gestures are off')
            self.description.setStringValue_(
                'Nothing here controls your Mac.' if self.mode == 'practice'
                else 'STARK follows your hands. Switch it off whenever you want a break.' if active
                else 'Turn STARK on to move, click, scroll and run shortcuts with your hands.')
            self.success.setStringValue_('Both fists for a second also stops STARK.' if active
                                         else 'Camera off. Nothing recognized.')
            self.primary.setTitle_('Turn gestures off' if active else 'Turn gestures on')
            self.primary.setEnabled_(self.ready and not self.fatal and not self.editing())
            self.secondary.setTitle_('Show me how')
        paint_primary(self.primary)
        on = self.mode != 'off' or self.requested_mode != 'off'
        self.menu_toggle.setTitle_('Turn gestures off' if on else 'Turn gestures on')
        self.status_item.button().setTitle_('STARK ●' if self.mode != 'off' else 'STARK ◉' if self.clap_listener else 'STARK ○')
        self.mic_note.setStringValue_(self.mic_message)
        if self.compact is not None:
            self.mini_toggle.setTitle_('Stop' if on else 'Start')
            self.mini_status.setStringValue_(self.error or (self.feedback.stringValue() if on else self.mic_message))
            if not on: self.mini_preview.setImage_(None)
        self.status_item.button().setToolTip_(
            f'STARK: {"practicing" if self.mode == "practice" else "gestures on" if self.mode == "control" else "gestures off"}')

    @objc.python_method
    def showRest(self, title='Standing by.', copy='Camera off. Move freely.'):
        self.preview.setImage_(None)
        for view in (self.rest_icon, self.rest_title, self.rest_copy):
            view.setHidden_(False)
        self.rest_title.setStringValue_(title)
        self.rest_copy.setStringValue_(copy)

    def refresh_(self, timer):
        if self.closing:
            if not self.worker.is_alive():
                self.timer.invalidate()
                A.NSApp.terminate_(None)
            return
        self.updateClap()
        if self.awaiting_access:
            self.pollAccess()
        data = None
        while True:
            try:
                data = self.worker.messages.get_nowait()
            except queue.Empty:
                break
        if data is None:
            return
        self.ready = data.get('ready', self.ready)
        self.config = data.get('cfg', self.config)
        self.bindings = data.get('bindings', self.bindings)
        self.camera_names = data.get('names', self.camera_names)
        self.camera_index = data.get('index', self.camera_index)
        if self.requested_mode == 'off' and data.get('mode', 'off') != 'off':
            return
        self.mode = data.get('mode', self.mode)
        if data.get('error'):
            self.error = data['error']
            self.busy = False
            self.requested_mode = 'off'
            if 'Accessibility' in self.error:
                # Permission was withdrawn mid-session: same guided flow, no dead end.
                self.beginAccessWait(prompt=False)
                return
            self.privacy_button.setHidden_(False)
        self.fatal = data.get('fatal', False) or self.fatal
        if data.get('clear') and not self.awaiting_access:
            self.requested_mode = 'off'
            self.showRest('Let’s sort this out.' if self.error else 'Standing by.',
                          self.error or 'Camera off. Move freely.')
            self.camera_note.setStringValue_('Camera off · nothing is being recognized')
            self.feedback.setStringValue_('STARK is off.' if not self.error else 'One thing needs attention.')
            self.busy = False
        if data.get('loading'):
            self.showRest('One moment…', data.get('message', 'Opening your camera…'))
        if data.get('image') and self.requested_mode != 'off':
            raw = data['image']
            decoded = A.NSImage.alloc().initWithData_(F.NSData.dataWithBytes_length_(raw, len(raw)))
            if decoded:
                iw, ih = decoded.size()
                scale = min(660 / max(iw, 1), 494 / max(ih, 1))
                pw, ph = iw * scale, ih * scale
                self.preview.setFrame_((((660 - pw) / 2, (494 - ph) / 2), (pw, ph)))
                self.preview.setImage_(decoded)
                if self.compact is not None: self.mini_preview.setImage_(decoded)
            for view in (self.rest_icon, self.rest_title, self.rest_copy):
                view.setHidden_(True)
            self.busy = False
            hands = data.get('hands', 0)
            self.camera_note.setStringValue_('Practice only · your real pointer stays put'
                                             if self.mode == 'practice'
                                             else 'Live on this Mac · video is never saved')
            event = data.get('event')
            self.feedback.setStringValue_(
                data.get('guard') or ('Dictation is listening…' if data.get('status', {}).get('dictating')
                else (event[:1].upper() + event[1:] if event
                      else 'Tracking your hands.' if hands else 'Bring your hands into view.')))
        if self.onboarding:
            self.lesson.observe(data)
        self.renderPanel()

    # ------------------------------------------------------------ modes
    @objc.python_method
    def requestMode(self, mode):
        if mode == 'off':
            self.endAccessWait()
            self.requested_mode = 'off'
            self.mode = 'off'
            self.busy = False
            self.worker.request('mode', 'off')
            self.showRest()
            self.camera_note.setStringValue_('Stopping camera and gestures…')
            self.renderPanel()
            return
        if self.busy or self.editing() or self.fatal or not self.ready:
            return
        self.error = ''
        self.privacy_button.setHidden_(True)
        self.fix_button.setHidden_(True)
        if self.args.dry_run:
            mode = 'practice'
        self.requested_mode = mode
        status = AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeVideo)
        if status == 0:
            self.busy = True
            self.showRest('Let STARK see your hands.',
                          'Choose Allow in the camera prompt. Video stays on this Mac.')
            self.renderPanel()

            def reply(granted):
                self.performSelectorOnMainThread_withObject_waitUntilDone_(
                    'cameraPermissionReturned:', bool(granted), False)
            AV.AVCaptureDevice.requestAccessForMediaType_completionHandler_(AV.AVMediaTypeVideo, reply)
            return
        if status != 3:
            self.permissionError('Allow STARK under Camera in Privacy & Security, then try again.')
            return
        if mode == 'control' and not ax_trusted():
            self.requested_mode = 'off'
            self.beginAccessWait()
            return
        self.busy = True
        self.worker.request('mode', mode)
        self.renderPanel()

    @objc.python_method
    def permissionError(self, message):
        self.error = message
        self.requested_mode = 'off'
        self.mode = 'off'
        self.busy = False
        self.showRest('One small step.', message)
        self.privacy_button.setHidden_(False)
        self.renderPanel()

    def cameraPermissionReturned_(self, granted):
        self.busy = False
        if self.closing or self.requested_mode == 'off':
            return
        if granted:
            self.requestMode(self.requested_mode)
        else:
            self.permissionError('Camera access is off. You can allow STARK later in Privacy & Security.')

    # ------------------------------------------------------------ accessibility
    @objc.python_method
    def beginAccessWait(self, prompt=True):
        """Guide the one-time Accessibility grant, then continue on our own.
        Never loops back to "turn gestures on"."""
        self.awaiting_access = True
        self.access_since = time.monotonic()
        self.access_checked = 0.0
        self.access_hint = False
        self.error = 'Accessibility'
        self.mode = 'off'
        self.busy = False
        if prompt and not self.test_mode:
            ax_trusted(prompt=True)          # registers STARK in the list
            self.openPrivacy_(None)
        self.showRest('Let STARK move the pointer.',
                      'System Settings › Privacy & Security › Accessibility\n'
                      'Turn on STARK. STARK starts by itself the moment it’s allowed.')
        self.camera_note.setStringValue_('Camera off · waiting for permission')
        self.feedback.setStringValue_('Waiting for Accessibility permission…')
        self.privacy_button.setHidden_(False)
        self.fix_button.setHidden_(False)
        self.renderPanel()

    @objc.python_method
    def pollAccess(self):
        now = time.monotonic()
        if now - self.access_checked < .75:
            return
        self.access_checked = now
        if ax_trusted():
            self.endAccessWait()
            self.feedback.setStringValue_('Permission granted. Starting gestures…')
            self.requestMode('control')
        elif now - self.access_since > 20 and not self.access_hint:
            self.access_hint = True
            self.rest_copy.setStringValue_(
                'STARK already shows On? That switch belongs to an older copy.\n'
                'Click Fix permission, then turn STARK on once more.')

    @objc.python_method
    def endAccessWait(self):
        if not getattr(self, 'awaiting_access', False):
            return
        self.awaiting_access = False
        self.error = ''
        self.privacy_button.setHidden_(True)
        self.fix_button.setHidden_(True)
        self.showRest()
        self.feedback.setStringValue_('Ready when you are.')
        self.renderPanel()

    def fixPermission_(self, sender):
        bundle = F.NSBundle.mainBundle().bundleIdentifier()
        if bundle != BUNDLE_ID:
            self.alert('Open STARK from the Dock', 'This fix works in the STARK app itself.')
            return
        alert = A.NSAlert.alloc().init()
        alert.setMessageText_('Reset STARK’s Accessibility permission?')
        alert.setInformativeText_('STARK clears its old entry and asks again. Then turn on STARK in '
                                  'the Accessibility list once more. Nothing else changes.')
        alert.addButtonWithTitle_('Reset and ask again')
        alert.addButtonWithTitle_('Cancel')
        if alert.runModal() != A.NSAlertFirstButtonReturn:
            return
        result = subprocess.run(['/usr/bin/tccutil', 'reset', 'Accessibility', BUNDLE_ID],
                                capture_output=True, text=True)
        if result.returncode != 0:
            self.alert('Do this one by hand',
                       'In Accessibility settings, select STARK, click the − button, then click '
                       'Turn gestures on in STARK again. STARK adds itself back.')
        ax_trusted(prompt=True)
        self.openPrivacy_(None)
        self.access_since = time.monotonic()
        self.access_hint = False

    def openPrivacy_(self, sender):
        topic = 'Privacy_Accessibility' if 'Accessibility' in self.error or self.awaiting_access \
            else 'Privacy_Camera'
        A.NSWorkspace.sharedWorkspace().openURL_(F.NSURL.URLWithString_(PRIVACY + topic))

    # ------------------------------------------------------------ actions
    def primaryAction_(self, sender):
        if self.awaiting_access:
            self.openPrivacy_(sender)
            return
        if not self.onboarding:
            self.toggleGestures_(sender)
            return
        step = self.lesson.step
        if step == 0:
            self.lesson.reset(1)
            self.requestMode('practice')
        elif step == 5:
            self.requestMode('off')
            self.lesson.reset(6)
        elif step == 6:
            self.finishLesson()
        elif self.mode == 'off':
            self.requestMode('practice')
        else:
            self.lesson.reset(step + 1)
        self.renderPanel()

    def secondaryAction_(self, sender):
        if self.awaiting_access:
            self.endAccessWait()
            return
        if self.onboarding and self.lesson.step != 6:
            self.finishLesson()
        else:
            self.startLesson_(sender)

    def toggleGestures_(self, sender):
        if self.mode != 'off' or self.requested_mode != 'off' or self.awaiting_access:
            self.requestMode('off')
        elif self.onboarding:
            self.showWindow_(None)
            if self.lesson.step == 0:
                self.lesson.reset(1)
            if self.lesson.step < 5:
                self.requestMode('practice')
        else:
            self.requestMode('control')
            if self.awaiting_access:
                self.showWindow_(None)

    def startLesson_(self, sender):
        self.closeSettings()
        self.closeControls()
        self.requestMode('off')
        self.onboarding = True
        self.lesson.reset(0)
        self.renderPanel()
        self.showWindow_(None)

    @objc.python_method
    def finishLesson(self):
        self.requestMode('off')
        self.onboarding = False
        F.NSUserDefaults.standardUserDefaults().setBool_forKey_(True, 'DexHasSeenWelcome')
        self.renderPanel()

    def previousLesson_(self, sender):
        self.lesson.reset(max(0, self.lesson.step - 1))
        if self.lesson.step == 0:
            self.requestMode('off')
        self.renderPanel()

    def skipLesson_(self, sender):
        if self.lesson.step == 5:
            self.requestMode('off')
        self.lesson.reset(min(6, self.lesson.step + 1))
        self.renderPanel()

    def showWindow_(self, sender):
        if self.compact is not None: self.compact.orderOut_(None)
        self.window.makeKeyAndOrderFront_(None)
        A.NSApp.activateIgnoringOtherApps_(True)

    def showCompact_(self, sender):
        if self.onboarding or self.editing():
            self.alert('Finish this step first', 'Finish or skip the walkthrough and close Settings or Controls, then use Mini preview.')
            return
        if self.compact is None:
            self.compact = A.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                ((0,0),(280,252)), A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable |
                A.NSWindowStyleMaskNonactivatingPanel, A.NSBackingStoreBuffered, False)
            self.compact.setTitle_('STARK · Mini preview')
            self.compact.setBackgroundColor_(BACKGROUND)
            self.compact.setReleasedWhenClosed_(False)
            self.compact.setDelegate_(self)
            self.compact.setLevel_(A.NSFloatingWindowLevel)
            self.compact.setHidesOnDeactivate_(False)
            self.compact.setCollectionBehavior_(A.NSWindowCollectionBehaviorCanJoinAllSpaces |
                                               A.NSWindowCollectionBehaviorFullScreenAuxiliary)
            root=self.compact.contentView()
            self.mini_preview=image_view(root,None,0,64,280,188)
            self.mini_status=label(root,'Gestures off',10,39,260,22,11,muted=True)
            self.mini_toggle=button(root,'Start',5,2,85,self,'toggleGestures:',height=32)
            button(root,'Expand',94,2,85,self,'showWindow:',height=32)
            button(root,'Settings',183,2,92,self,'openSettings:',height=32)
        screen=self.window.screen() or A.NSScreen.mainScreen()
        area=screen.visibleFrame(); frame=self.compact.frame()
        self.compact.setFrameOrigin_((area.origin.x+area.size.width-frame.size.width-16,area.origin.y+16))
        self.mini_preview.setImage_(self.preview.image())
        self.window.orderOut_(None)
        if not self.test_mode: self.compact.orderFrontRegardless()
        self.renderPanel()

    @objc.python_method
    def updateClap(self):
        enabled=bool(self.config.get('clap_wake'))
        eligible=enabled and self.mode=='off' and self.requested_mode=='off' and not self.editing() and not self.onboarding and not self.awaiting_access and not self.busy and not self.fatal
        if not eligible:
            if self.clap_listener: self.clap_listener.close(); self.clap_listener=None
            self.mic_message='Double-clap wake paused' if enabled else 'Double-clap wake off'
            self.mic_note.setStringValue_(self.mic_message)
            return
        if self.test_mode: return
        status=AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeAudio)
        if status != 3:
            self.mic_message='Double-clap wake needs Microphone permission in Settings'
        elif not self.clap_failed:
            try:
                if self.clap_listener is None:
                    from clap import ClapListener
                    self.clap_listener=ClapListener()
                self.mic_message='Listening for two claps · microphone on'
                if self.clap_listener.poll():
                    self.clap_listener.close(); self.clap_listener=None
                    self.requestMode('control')
                    self.mic_message='Double clap detected'
            except Exception as error:
                if self.clap_listener: self.clap_listener.close(); self.clap_listener=None
                self.clap_failed=True
                self.mic_message=str(error)
        self.mic_note.setStringValue_(self.mic_message)
        self.renderPanel()

    def microphonePermissionReturned_(self, granted):
        self.mic_pending=False
        self.clap_failed=False
        if not granted:
            self.alert('Microphone access is off', 'Double-clap wake needs Microphone permission for STARK in System Settings → Privacy & Security. Gesture controls still work without it.')
        self.updateClap()

    def applicationShouldHandleReopen_hasVisibleWindows_(self, app, visible):
        self.showWindow_(None)
        return True

    def about_(self, sender):
        self.alert('STARK', 'Spatial Tracking and Recognition Kit.\n\nHands-free control for your Mac.\n\nSTARK runs the HandControl engine in '
                   'the HandControl folder on your Desktop. Video is processed on this Mac and '
                   'never recorded.\n\n⌃⌥M turns gestures on or off from any app.')

    @objc.python_method
    def alert(self, title, message):
        if self.test_mode:
            self.last_alert = (title, message)
            return
        alert = A.NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        alert.runModal()

    # ------------------------------------------------------------ settings
    def openSettings_(self, sender):
        if self.settings is not None:
            self.settings.makeKeyAndOrderFront_(None)
            return
        self.closeControls()
        self.requestMode('off')
        self.worker.request('suspend', True)
        self.settings = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((180, 180), (520, 730)), A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable,
            A.NSBackingStoreBuffered, False)
        self.settings.setTitle_('STARK Settings')
        self.settings.setBackgroundColor_(BACKGROUND)
        self.settings.setReleasedWhenClosed_(False)
        self.settings.setDelegate_(self)
        root = self.settings.contentView()
        label(root, 'Settings', 24, 499, 470, 30, 23, True)
        label(root, 'Gestures stay off while you make changes.', 24, 470, 465, 23, 13, muted=True)
        label(root, 'Pointer hand', 24, 424, 235)
        self.hand_choice = A.NSPopUpButton.alloc().initWithFrame_pullsDown_(((300, 420), (193, 30)), False)
        self.hand_choice.addItemsWithTitles_(['Right hand', 'Left hand'])
        self.hand_choice.selectItemAtIndex_(int(bool(self.config['swap_hands'])))
        root.addSubview_(self.hand_choice)
        label(root, 'Camera', 24, 381, 235)
        self.camera_choice = A.NSPopUpButton.alloc().initWithFrame_pullsDown_(((244, 377), (250, 30)), False)
        import handcontrol as hc
        devices=hc.camera_devices()
        self.camera_options=['auto']+['id:'+d['id'] for d in devices]
        self.camera_choice.addItemsWithTitles_(['Automatic · laptop / webcam only'] +
            [d['name']+(' (phone · opt-in)' if d['phone'] else '') for d in devices])
        selected=self.config.get('camera','auto')
        if selected in self.camera_options:
            self.camera_choice.selectItemAtIndex_(self.camera_options.index(selected))
        root.addSubview_(self.camera_choice)
        self.sliders = {}
        for key, title, y, low, high in [('smoothing_min_cutoff', 'Pointer feel', 320, .1, 4),
                                         ('scroll_gain', 'Scroll speed', 243, 100, 6000)]:
            label(root, title, 24, y + 24, 220)
            slider = A.NSSlider.alloc().initWithFrame_(((24, y), (468, 24)))
            slider.setMinValue_(low)
            slider.setMaxValue_(high)
            slider.setDoubleValue_(self.config[key])
            root.addSubview_(slider)
            self.sliders[key] = slider
            label(root, 'Steady' if key == 'smoothing_min_cutoff' else 'Gentle', 24, y - 20, 210, 22, 12, muted=True)
            right = label(root, 'Quick' if key == 'smoothing_min_cutoff' else 'Fast', 280, y - 20, 211, 22, 12, muted=True)
            right.setAlignment_(A.NSTextAlignmentRight)
        self.checks = {}
        for i, (key, title) in enumerate([('invert_scroll', 'Reverse scroll direction'),
                                          ('dictation', 'Dictation gesture (Wispr Flow)')]):
            b = button(root, title, 21, 166 - i * 34, 468, self, 'noop:')
            b.setButtonType_(A.NSButtonTypeSwitch)
            b.setState_(int(bool(self.config[key])))
            self.checks[key] = b
        label(root, 'Gesture mappings live in Controls.', 26, 103, 464, 22, 12, muted=True)
        button(root, 'Fine-tune…', 21, 18, 122, self, 'advancedSettings:')
        button(root, 'Cancel', 281, 18, 100, self, 'cancelSettings:')
        button(root, 'Save', 389, 18, 108, self, 'saveSettings:', True)
        self.advanced_values = {key: self.config[key] for key, _, _, _ in FIELDS}
        # Make space for new opt-in controls without crowding the original settings.
        for view in root.subviews():
            frame=view.frame()
            if frame.origin.y > 60:
                view.setFrameOrigin_((frame.origin.x,frame.origin.y+180))
        for key,title,y in [('gesture_guard','Gesture guard · open palm to arm, filter brief pinches',225),
                            ('clap_wake','Double-clap wake · use microphone while STARK is off',189)]:
            b=button(root,title,21,y,478,self,'noop:')
            b.setButtonType_(A.NSButtonTypeSwitch)
            b.setState_(int(bool(self.config.get(key,key=='gesture_guard'))))
            self.checks[key]=b
        label(root,'Clap twice, about half a second apart. STARK must stay running.\nAudio is processed locally and never saved. Uses your Mac’s selected sound input.',26,112,468,66,12,muted=True)
        label(root,'Pointer spans all connected displays. Mini preview stays above other windows.',26,65,468,42,12,muted=True)
        self.settings.center()
        if not self.test_mode:
            self.settings.makeKeyAndOrderFront_(None)
        self.renderPanel()

    def advancedSettings_(self, sender):
        alert = A.NSAlert.alloc().init()
        alert.setMessageText_('Fine-tune your gestures')
        alert.setInformativeText_('Smaller pinch values need a tighter pinch. Applied when you save Settings.')
        view = A.NSView.alloc().initWithFrame_(((0, 0), (420, 130)))
        fields = {}
        for i, (key, title) in enumerate([('pinch_press', 'Pinch sensitivity'),
                                          ('pinch_release', 'Release threshold'),
                                          ('tap_hold_s', 'Hold time (seconds)')]):
            y = 94 - i * 40
            label(view, title, 0, y, 290)
            field = A.NSTextField.alloc().initWithFrame_(((310, y), (100, 25)))
            field.setStringValue_(str(self.advanced_values[key]))
            view.addSubview_(field)
            fields[key] = field
        alert.setAccessoryView_(view)
        alert.addButtonWithTitle_('Done')
        alert.addButtonWithTitle_('Cancel')
        if alert.runModal() == A.NSAlertFirstButtonReturn:
            try:
                self.advanced_values.update(validate_settings(
                    dict(self.advanced_values, **{k: v.stringValue() for k, v in fields.items()})))
            except ValueError as error:
                self.alert('Try a different value', str(error))

    def noop_(self, sender):
        pass

    def saveSettings_(self, sender):
        try:
            values = dict(self.advanced_values, **{k: v.doubleValue() for k, v in self.sliders.items()})
            updates = validate_settings(values)
            updates.update({k: bool(v.state()) for k, v in self.checks.items()})
            updates['swap_hands'] = bool(self.hand_choice.indexOfSelectedItem())
            selection = self.camera_options[int(self.camera_choice.indexOfSelectedItem())]
            updates['camera'] = selection
            save_settings(self.config_path, updates)
        except (ValueError, OSError) as error:
            self.alert('Settings weren’t saved', str(error))
            return
        self.config.update(updates)
        self.worker.request('configure', updates)
        self.worker.request('select', selection)
        self.closeSettings()
        self.clap_failed=False
        if updates.get('clap_wake') and not self.test_mode:
            status=AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeAudio)
            if status==0 and not self.mic_pending:
                self.mic_pending=True
                def reply(granted):
                    self.performSelectorOnMainThread_withObject_waitUntilDone_('microphonePermissionReturned:',bool(granted),False)
                AV.AVCaptureDevice.requestAccessForMediaType_completionHandler_(AV.AVMediaTypeAudio,reply)
            elif status!=3:
                self.alert('Allow microphone access', 'Open System Settings → Privacy & Security → Microphone and enable STARK. Double-clap wake is optional.')
        self.updateClap()

    def cancelSettings_(self, sender):
        self.closeSettings()

    @objc.python_method
    def closeSettings(self):
        window, self.settings = self.settings, None
        if window is not None:
            self.worker.request('suspend', False)
            self.renderPanel()
            window.close()

    # ------------------------------------------------------------ controls
    def showGuide_(self, sender):
        self.openControls_(sender)

    def openControls_(self, sender):
        if self.controls is not None:
            self.controls.makeKeyAndOrderFront_(None)
            return
        self.closeSettings()
        self.requestMode('off')
        self.worker.request('suspend', True)
        current = dict(DEFAULT_BINDINGS)
        current.update(self.bindings or {})
        self.edited = {k: current.get(k) for k in C.BINDABLE_KEYS}
        self.edited_cfg = {k: self.config.get(k, DEFAULTS[k])
                           for k in ('dictation_key', 'dictation_hands_free_key')}
        W, H = 900, 660
        self.controls = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((140, 120), (W, H)), A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable,
            A.NSBackingStoreBuffered, False)
        self.controls.setTitle_('STARK Controls')
        self.controls.setBackgroundColor_(BACKGROUND)
        self.controls.setReleasedWhenClosed_(False)
        self.controls.setDelegate_(self)
        root = self.controls.contentView()
        label(root, 'Controls', 24, H - 60, 400, 36, 26, True)
        label(root, 'Every gesture, what it does, and the exact key or click STARK sends. '
                    'Click an input to record a new one.', 24, H - 88, 600, 22, 13, muted=True)
        self.search_field = A.NSSearchField.alloc().initWithFrame_(((W - 264, H - 54), (240, 28)))
        self.search_field.setPlaceholderString_('Search controls')
        self.search_field.setTarget_(self)
        self.search_field.setAction_('searchControls:')
        root.addSubview_(self.search_field)
        for text, x in (('GESTURE', 36), ('HAND', 350), ('ACTION', 470), ('INPUT', 714)):
            label(root, text, x, H - 124, 200, 18, 11, True, True)
        self.controls_scroll = A.NSScrollView.alloc().initWithFrame_(((24, 68), (W - 48, H - 196)))
        self.controls_scroll.setHasVerticalScroller_(True)
        self.controls_scroll.setBorderType_(A.NSNoBorder)
        self.controls_scroll.setDrawsBackground_(False)
        root.addSubview_(self.controls_scroll)
        self.record_note = label(root, 'Gestures stay off while Controls is open.', 196, 24, 380, 22, 12, muted=True)
        button(root, 'Restore Defaults', 24, 16, 160, self, 'restoreControls:')
        button(root, 'Cancel', W - 252, 16, 100, self, 'cancelControls:')
        button(root, 'Save', W - 144, 16, 120, self, 'saveControls:', True)
        self.controls_filter = ''
        self.buildControlRows(keep_scroll=False)
        self.controls.center()
        if not self.test_mode:
            self.controls.makeKeyAndOrderFront_(None)
        self.renderPanel()

    @objc.python_method
    def buildControlRows(self, keep_scroll=True):
        scroll = self.controls_scroll
        origin = scroll.contentView().bounds().origin if keep_scroll else (0, 0)
        cfg = dict(self.config)
        cfg.update(self.edited_cfg)
        rows = C.search(C.catalog(self.edited, cfg), self.controls_filter)
        width = scroll.contentSize().width
        doc = FlippedView.alloc().initWithFrame_(((0, 0), (width, 10)))
        self.row_keys, self.row_popups, self.row_caps = [], {}, {}
        mono = A.NSFont.monospacedSystemFontOfSize_weight_(13, A.NSFontWeightMedium)
        lock = None
        try:
            lock = A.NSImage.imageWithSystemSymbolName_accessibilityDescription_('lock.fill', 'Built in')
        except Exception:
            pass
        y, category = 6, None
        for row in rows:
            if row['category'] != category:
                category = row['category']
                y += 12 if y > 6 else 0
                head = label(doc, category.upper(), 12, y, 400, 20, 12, True)
                head.setTextColor_(ACCENT)
                y += 26
            tag = len(self.row_keys)
            self.row_keys.append(row['key'])
            label(doc, row['gesture'], 12, y + 9, 314, 20, 13)
            label(doc, row['hand'], 326, y + 9, 116, 20, 12, muted=True)
            if row['editable']:
                self.row_popups[row['key']] = self.actionPopup(doc, row['key'], tag, 442, y + 4, 240)
            else:
                label(doc, row['action'], 446, y + 9, 236, 20, 13)
            cap = A.NSButton.alloc().initWithFrame_(((690, y + 3), (width - 702, 32)))
            cap.setBezelStyle_(A.NSBezelStyleRounded)
            cap.setFont_(mono)
            cap.setTitle_(row['input'])
            cap.setTag_(tag)
            recordable = row['editable'] or row['key'] == 'fixed.dictate'
            if recordable:
                cap.setTarget_(self)
                cap.setAction_('recordControl:')
                cap.setToolTip_('Click, then press the new shortcut. Esc cancels.')
            else:
                cap.setEnabled_(False)
                cap.setToolTip_('Built in')
                if lock is not None:
                    cap.setImage_(lock)
                    cap.setImagePosition_(getattr(A, 'NSImageLeading', A.NSImageLeft))
            doc.addSubview_(cap)
            self.row_caps[row['key']] = cap
            y += 40
        if not rows:
            label(doc, 'No controls match your search.', 12, 16, 400, 22, 13, muted=True)
            y = 50
        doc.setFrameSize_((width, max(y + 10, scroll.contentSize().height)))
        scroll.setDocumentView_(doc)
        scroll.contentView().scrollToPoint_(origin)
        scroll.reflectScrolledClipView_(scroll.contentView())

    @objc.python_method
    def actionPopup(self, parent, key, tag, x, y, w):
        popup = A.NSPopUpButton.alloc().initWithFrame_pullsDown_(((x, y), (w, 30)), False)
        popup.setAutoenablesItems_(False)
        menu = popup.menu()
        value = self.edited.get(key)

        def add(title, rep, enabled=True, indent=0):
            item = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, '')
            item.setRepresentedObject_(rep)
            item.setEnabled_(enabled)
            item.setIndentationLevel_(indent)
            menu.addItem_(item)
            return item

        add('Not assigned', '')
        if value and value not in C.ACTION_LABELS:
            add(f'Custom: {C.format_combo(value)}', value)
        for group, names in C.ACTION_GROUPS:
            menu.addItem_(A.NSMenuItem.separatorItem())
            add(group, None, enabled=False)
            for name in names:
                add(f'{C.ACTION_LABELS[name]}   {C.input_for(name)}', name, indent=1)
        for i in range(menu.numberOfItems()):
            item = menu.itemAtIndex_(i)
            if item.isEnabled() and item.representedObject() == (value or ''):
                popup.selectItemAtIndex_(i)
                break
        popup.setTarget_(self)
        popup.setAction_('actionPicked:')
        popup.setTag_(tag)
        parent.addSubview_(popup)
        return popup

    def actionPicked_(self, sender):
        key = self.row_keys[sender.tag()]
        rep = sender.selectedItem().representedObject()
        self.edited[key] = str(rep) if rep else None
        # Update in place: rebuilding would remove the menu that is sending this.
        self.row_caps[key].setTitle_(C.input_for(self.edited[key]))
        self.record_note.setStringValue_(f'{C.action_label(self.edited[key])} · save to keep it.')

    def recordControl_(self, sender):
        self.stopRecording()
        key = self.row_keys[sender.tag()]
        self.recording_key = key
        self.recorder = C.Recorder(allow_modifier_only=(key == 'fixed.dictate'))
        sender.setTitle_('Press keys…')
        self.record_note.setStringValue_(
            'Press the new shortcut now. Esc cancels.' +
            (' A modifier alone works, like fn.' if key == 'fixed.dictate' else ''))
        handler = lambda event: self.handleRecordEvent(event)
        self._record_handler = handler
        if not self.test_mode:
            self.monitor = A.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                A.NSEventMaskKeyDown | A.NSEventMaskFlagsChanged, handler)

    @objc.python_method
    def handleRecordEvent(self, event):
        if self.recorder is None:
            return event
        kind = event.type()
        if kind == A.NSEventTypeKeyDown:
            self.recorder.key_down(event.keyCode(), event.modifierFlags())
        elif kind == A.NSEventTypeFlagsChanged:
            self.recorder.flags_changed(event.modifierFlags())
        if self.recorder.done:
            self.finishRecording()
        return None          # swallow keys while recording (⌘Q won't quit)

    @objc.python_method
    def finishRecording(self):
        key, recorder = self.recording_key, self.recorder
        self.stopRecording()
        if recorder.result:
            try:
                if key == 'fixed.dictate':
                    name = ('dictation_hands_free_key' if self.config.get('dictation_mode') == 'hands_free'
                            else 'dictation_key')
                    self.edited_cfg[name] = C.normalize_combo(recorder.result)
                else:
                    self.edited[key] = C.action_for_combo(recorder.result)
                self.record_note.setStringValue_(f'Recorded {C.format_combo(recorder.result)} · save to keep it.')
            except ValueError as error:
                self.record_note.setStringValue_(str(error))
        else:
            self.record_note.setStringValue_('Recording cancelled.')
        self.scheduleRebuild()

    @objc.python_method
    def scheduleRebuild(self):
        if self.test_mode:
            self.buildControlRows()
        else:
            self.performSelector_withObject_afterDelay_('rebuildControls:', None, 0)

    def rebuildControls_(self, _):
        if self.controls is not None:
            self.buildControlRows()

    @objc.python_method
    def stopRecording(self):
        if self.monitor is not None:
            A.NSEvent.removeMonitor_(self.monitor)
            self.monitor = None
        self.recorder = None
        self.recording_key = None

    def searchControls_(self, sender):
        self.controls_filter = str(sender.stringValue())
        self.buildControlRows(keep_scroll=False)

    def restoreControls_(self, sender):
        self.stopRecording()
        self.edited = {k: DEFAULT_BINDINGS.get(k) for k in C.BINDABLE_KEYS}
        self.edited_cfg = {k: DEFAULTS[k] for k in ('dictation_key', 'dictation_hands_free_key')}
        self.record_note.setStringValue_('Defaults restored · save to keep them.')
        self.buildControlRows(keep_scroll=False)

    def saveControls_(self, sender):
        self.stopRecording()
        try:
            C.save_bindings(self.config_path, self.edited)
            cfg_changes = {k: v for k, v in self.edited_cfg.items() if self.config.get(k) != v}
            if cfg_changes:
                save_settings(self.config_path, cfg_changes)
        except (ValueError, OSError) as error:
            self.alert('Controls weren’t saved', str(error))
            return
        self.bindings = dict(self.edited)
        self.config.update(self.edited_cfg)
        self.worker.request('bindings', dict(self.edited))
        if cfg_changes:
            self.worker.request('configure', cfg_changes)
        self.feedback.setStringValue_('Controls saved.')
        self.closeControls()

    def cancelControls_(self, sender):
        self.closeControls()

    @objc.python_method
    def closeControls(self):
        window, self.controls = self.controls, None
        if window is not None:
            self.stopRecording()
            self.worker.request('suspend', False)
            self.renderPanel()
            window.close()

    # ------------------------------------------------------------ lifecycle
    def windowWillClose_(self, notification):
        window = notification.object()
        if self.settings is not None and window == self.settings:
            self.closeSettings()          # red close button
        elif self.controls is not None and window == self.controls:
            self.closeControls()
        elif window == self.window or window == self.compact:
            self.requestMode('off')

    def applicationShouldTerminate_(self, app):
        self.closing = True
        if self.clap_listener: self.clap_listener.close(); self.clap_listener=None
        if self.compact is not None: self.compact.orderOut_(None)
        self.worker.output_allowed.clear()
        self.worker.stop.set()
        self.window.orderOut_(None)
        if self.worker.is_alive():
            return A.NSTerminateCancel
        if self.hotkey:
            self.hotkey.close()
        A.NSStatusBar.systemStatusBar().removeStatusItem_(self.status_item)
        return A.NSTerminateNow


def run(args):
    app = A.NSApplication.sharedApplication()
    app.setActivationPolicy_(A.NSApplicationActivationPolicyRegular)
    delegate = Desktop.alloc().init()
    delegate.args = args
    app.setDelegate_(delegate)
    app.run()
    return 0


# ---------------------------------------------------------------- self-check
def snapshot(view, path):
    rect = view.bounds()
    rep = view.bitmapImageRepForCachingDisplayInRect_(rect)
    view.cacheDisplayInRect_toBitmapImageRep_(rect, rep)
    rep.representationUsingType_properties_(A.NSBitmapImageFileTypePNG, {}).writeToFile_atomically_(path, True)


def selftest(out_dir):
    """Build every window offscreen, drive the Controls editor and the
    permission flow, save screenshots and results. Never touches config.json
    or the camera, and never moves the pointer."""
    import json
    import shutil
    import tempfile
    import traceback
    import types
    import handcontrol as hc
    os.makedirs(out_dir, exist_ok=True)
    results = []

    def check(name, ok, detail=''):
        results.append({'name': name, 'ok': bool(ok), 'detail': str(detail)})

    app = A.NSApplication.sharedApplication()
    app.setActivationPolicy_(A.NSApplicationActivationPolicyAccessory)
    temp = tempfile.mkdtemp()
    cfg_path = os.path.join(temp, 'config.json')
    shutil.copy(hc.CONFIG, cfg_path)
    d = Desktop.alloc().init()
    d.args = types.SimpleNamespace(dry_run=False, camera=None)
    d.test_mode = True
    d.config_path = cfg_path
    shot = lambda view, name: snapshot(view, os.path.join(out_dir, name))
    try:
        check('running as the STARK app', F.NSBundle.mainBundle().bundleIdentifier() == BUNDLE_ID,
              F.NSBundle.mainBundle().bundleIdentifier())
        check('accessibility currently allowed (informational)', True, ax_trusted())
        d.applicationDidFinishLaunching_(None)
        d.ready = True
        d.renderPanel()
        check('main window is STARK', d.window.title() == 'STARK')
        check('home says gestures are off', d.heading.stringValue() == 'Gestures are off', d.heading.stringValue())
        shot(d.window.contentView(), '1-home.png')

        d.beginAccessWait(prompt=False)
        check('permission flow shows guided setup',
              d.awaiting_access and d.primary.title() == 'Open Accessibility' and not d.fix_button.isHidden(),
              d.primary.title())
        shot(d.window.contentView(), '2-permission.png')
        d.secondaryAction_(None)
        check('cancel leaves the permission flow', not d.awaiting_access and d.fix_button.isHidden())

        d.openControls_(None)
        check('controls window opens', d.controls is not None and d.controls.title() == 'STARK Controls')
        check('every control is listed', len(d.row_keys) == len(C.catalog()), len(d.row_keys))
        check('gestures suspended while editing', not d.primary.isEnabled())
        shot(d.controls.contentView(), '3-controls.png')

        popup = d.row_popups['left.open.hold']
        index = next(i for i in range(popup.numberOfItems())
                     if popup.itemAtIndex_(i).representedObject() == 'reopen_tab')
        popup.selectItemAtIndex_(index)
        d.actionPicked_(popup)
        check('pick an action from the menu', d.edited['left.open.hold'] == 'reopen_tab', d.edited['left.open.hold'])
        check('input column updates', d.row_caps['left.open.hold'].title() == '⇧⌘T',
              d.row_caps['left.open.hold'].title())

        d.recordControl_(d.row_caps['left.middle.tap'])
        check('recording shows a prompt', d.row_caps['left.middle.tap'].title() == 'Press keys…')
        ev = A.NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
            A.NSEventTypeKeyDown, (0, 0), (1 << 20) | (1 << 17), 0, 0, None, 'k', 'k', False, 40)
        d.handleRecordEvent(ev)
        check('record a key combo', d.edited['left.middle.tap'] == 'shift+cmd+k', d.edited['left.middle.tap'])

        d.recordControl_(d.row_caps['fixed.dictate'])
        for flags in ((1 << 18), (1 << 18) | (1 << 19), 0):
            fe = A.NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
                A.NSEventTypeFlagsChanged, (0, 0), flags, 0, 0, None, '', '', False, 59)
            d.handleRecordEvent(fe)
        check('record a modifier-only dictation key', d.edited_cfg['dictation_key'] == 'ctrl+alt',
              d.edited_cfg['dictation_key'])

        d.recordControl_(d.row_caps['left.ring.tap'])
        esc = A.NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
            A.NSEventTypeKeyDown, (0, 0), 0, 0, 0, None, '\x1b', '\x1b', False, 53)
        d.handleRecordEvent(esc)
        check('Esc cancels recording', d.edited['left.ring.tap'] == 'paste', d.edited['left.ring.tap'])

        d.search_field.setStringValue_('wispr')
        d.searchControls_(d.search_field)
        check('search filters the list', d.row_keys == ['fixed.dictate'], d.row_keys)
        shot(d.controls.contentView(), '4-controls-search.png')
        d.search_field.setStringValue_('')
        d.searchControls_(d.search_field)

        d.saveControls_(None)
        saved = json.load(open(cfg_path))
        check('save writes the changes', saved['bindings'].get('left.open.hold') == 'reopen_tab'
              and saved['bindings'].get('left.middle.tap') == 'shift+cmd+k'
              and saved.get('dictation_key') == 'ctrl+alt', saved.get('bindings'))
        check('save keeps your other settings', saved.get('scroll_gain') == json.load(open(hc.CONFIG)).get('scroll_gain'))
        check('save closes the window', d.controls is None)
        check('engine receives new bindings', d.bindings.get('left.open.hold') == 'reopen_tab')

        d.openControls_(None)
        d.restoreControls_(None)
        check('restore defaults', d.edited['left.middle.tap'] == 'copy' and d.edited['left.open.hold'] is None)
        d.cancelControls_(None)
        check('cancel discards', json.load(open(cfg_path))['bindings'].get('left.open.hold') == 'reopen_tab')

        d.showCompact_(None)
        check('compact window floats', d.compact.level() == A.NSFloatingWindowLevel)
        check('compact includes stop and expand', d.mini_toggle.title() == 'Start')
        shot(d.compact.contentView(), '6-mini-preview.png')
        d.openSettings_(None)
        check('new optional settings present', 'clap_wake' in d.checks and 'gesture_guard' in d.checks)
        check('camera automatic option is safe', d.camera_options[0] == 'auto')
        check('settings window opens', d.settings is not None and d.settings.title() == 'STARK Settings')
        shot(d.settings.contentView(), '5-settings.png')
        d.cancelSettings_(None)

        titles = [d.status_item.menu().itemAtIndex_(i).title() for i in range(d.status_item.menu().numberOfItems())]
        check('menu bar has Controls', 'Controls…' in titles and 'Quit STARK' in titles, titles)
    except Exception:
        results.append({'name': 'unexpected error', 'ok': False, 'detail': traceback.format_exc()})
    finally:
        try:
            A.NSStatusBar.systemStatusBar().removeStatusItem_(d.status_item)
        except Exception:
            pass
        shutil.rmtree(temp, ignore_errors=True)
    with open(os.path.join(out_dir, 'results.json'), 'w') as f:
        json.dump(results, f, indent=1, ensure_ascii=False)
    failed = [r for r in results if not r['ok']]
    print(f'UI self-check: {len(results) - len(failed)}/{len(results)} passed')
    for r in failed:
        print('  FAILED:', r['name'], r['detail'])
    return 1 if failed else 0
