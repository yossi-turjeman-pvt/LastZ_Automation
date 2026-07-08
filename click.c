#include <ApplicationServices/ApplicationServices.h>
#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>

int main(int argc, char *argv[]) {
    if (argc < 3) {
        puts("Usage: click x y");
        return 1;
    }
    double x = atof(argv[1]);
    double y = atof(argv[2]);

    CGPoint pt = CGPointMake(x, y);
    
    // Move mouse
    CGEventRef move = CGEventCreateMouseEvent(NULL, kCGEventMouseMoved, pt, kCGMouseButtonLeft);
    CGEventPost(kCGHIDEventTap, move);
    CFRelease(move);
    usleep(150000); // 150ms

    // Mouse down
    CGEventRef down = CGEventCreateMouseEvent(NULL, kCGEventLeftMouseDown, pt, kCGMouseButtonLeft);
    CGEventPost(kCGHIDEventTap, down) ;
    CFRelease(down);
    
    // Hold down for 300ms so the game's polling loop catches the click state reliably
    usleep(300000); // 300ms

    // Mouse up
    CGEventRef up = CGEventCreateMouseEvent(NULL, kCGEventLeftMouseUp, pt, kCGMouseButtonLeft);
    CGEventPost(kCGHIDEventTap, up);
    CFRelease(up);
    usleep(150000); // 150ms

    return 0;
}
