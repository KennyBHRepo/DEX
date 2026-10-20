// In-process audio metering only. No recording, files, speech recognition or network.
#import <AVFoundation/AVFoundation.h>
#import <Foundation/Foundation.h>
#include <stdatomic.h>
#include <math.h>
#include <time.h>
typedef struct { double t, peak, rms; } Meter;
static Meter ring[256];
static _Atomic unsigned head=0, tail=0;
static AVAudioEngine *engine;
static BOOL tapped=NO;
void dex_audio_stop(void) {
    [engine stop];
    if (tapped) [engine.inputNode removeTapOnBus:0];
    tapped=NO; engine=nil;
    atomic_store(&head,0); atomic_store(&tail,0);
}
int dex_audio_running(void) { return engine && engine.isRunning; }
int dex_audio_start(void) {
    if (engine.isRunning) return 1;
    if ([AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeAudio] != AVAuthorizationStatusAuthorized) return 0;
    @try {
        dex_audio_stop();
        engine=[AVAudioEngine new];
        AVAudioInputNode *input=engine.inputNode;
        AVAudioFormat *format=[input outputFormatForBus:0];
        if (!format.channelCount || !format.sampleRate) { dex_audio_stop(); return 0; }
        [input installTapOnBus:0 bufferSize:512 format:format block:^(AVAudioPCMBuffer *buffer, AVAudioTime *when) {
            float *const *channels=buffer.floatChannelData;
            if (!channels || !buffer.frameLength) return;
            // Use actual sample times even if the device batches callbacks.
            double end=[AVAudioTime secondsForHostTime:when.hostTime];
            unsigned stride=MAX(1,(unsigned)(format.sampleRate*.01));
            for (unsigned base=0;base<buffer.frameLength;base+=stride) {
                unsigned count=MIN(stride,buffer.frameLength-base); double peak=0,sum=0;
                for (unsigned i=base;i<base+count;i++) { double v=channels[0][i]; peak=fmax(peak,fabs(v)); sum+=v*v; }
                unsigned h=atomic_load(&head), next=(h+1)%256;
                if(next==atomic_load(&tail)) continue; // bounded; never block audio thread
                ring[h]=(Meter){end+base/format.sampleRate,peak,sqrt(sum/count)};
                atomic_store(&head,next);
            }
        }];
        tapped=YES;
        NSError *error=nil;
        if (![engine startAndReturnError:&error]) { dex_audio_stop(); return 0; }
        return 1;
    } @catch(NSException *exception) { dex_audio_stop(); return 0; }
}
int dex_audio_read(double *t,double *peak,double *rms) {
    unsigned next=atomic_load(&tail);
    if(next==atomic_load(&head)) return 0;
    Meter m=ring[next]; *t=m.t;*peak=m.peak;*rms=m.rms;
    atomic_store(&tail,(next+1)%256); return 1;
}
