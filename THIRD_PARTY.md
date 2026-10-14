Hardware references: Waveshare LCD HAT pin assignments and ST7789VM register
initialization, as documented in Waveshare's 1.3-inch LCD HAT Python sample and
in RaspyJack's LCD_1in44.py:
https://www.waveshare.com/wiki/1.3inch_LCD_HAT
https://github.com/7h30th3r0n3/Raspyjack

Nightshade's application, menu, dashboard and script runner are independent.
The compact LCD initialization register tables follow Waveshare's sample and
the MIT-licensed Waveshare-derived driver distributed by RaspyJack. Its
permission notice:

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.

Additional manufacturer reference (ST7789VW reset quirk and GPIO wiring):
https://github.com/waveshareteam/waveshare_fbcp/blob/master/st7735r.cpp
https://github.com/waveshareteam/waveshare_fbcp/blob/master/waveshare_st7789vw_hat.h

Boot crest artwork: the DarkSec Labs boot splash uses "Skull and Crossbones.svg"
from Wikimedia Commons. It is in the public domain as an image of simple
geometry, ineligible for copyright:
https://commons.wikimedia.org/wiki/File:Skull_and_Crossbones.svg
The source is recoloured to the Nightshade palette and scaled to the panel; the
shipped file is nightshade/assets/darkseclabs.png.
