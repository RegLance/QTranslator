/**
 * Keyboard utility functions for macOS
 * Convert macOS virtual key codes to MDN KeyboardEvent.key values
 */

#import <Carbon/Carbon.h>

#import <string>
#import <unordered_map>

/**
 * Convert macOS virtual key code to MDN WebAPI KeyboardEvent.key value
 * @param keyCode The macOS virtual key code (CGKeyCode)
 * @param flags Event flags to determine modifier states
 * @return String representation of the key following MDN KeyboardEvent.key specification
 */
std::string convertKeyCodeToUniKey(CGKeyCode keyCode, CGEventFlags flags = 0);