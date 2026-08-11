# Free navigation between the Business Cards of one Photo

Confirmation moves between the Business Cards of a Photo freely — swiping the card image, or the arrows beside the "1 / 2" counter — instead of only forwards. Every detected card is always a page, including ones still being recognised, which show their recognition state in place rather than being hidden; the page count therefore matches what was detected and does not shift while recognition runs. Leaving a page with unsaved edits saves them as a draft: the Contact is written, but not confirmed, so an interrupted edit survives without quietly becoming a Confirmed Contact.

Because pages can be visited in any order, the flow ends when no unconfirmed Contact remains, not when the last page is confirmed — plus an explicit way to stop early. Detection now orders its candidates by position in the Photo, top row first and left to right within a row, since contour scan order is unrelated to layout and would otherwise make "card 1" the wrong card to anyone looking at the photo.

Swipe is confined to the card image. The confirmation screen is a form of fourteen inputs, and a screen-wide horizontal gesture would fight text selection and the cursor inside them.
