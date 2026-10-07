/* Keep tour captions inside the viewport area above the floating player. */
(function (root) {
  function placePopover({anchorTop, anchorBottom, height, playerTop, viewportHeight, side = 'bottom'}) {
    const gap = 14;
    const bottom = Math.max(gap + 1, Math.min(playerTop, viewportHeight) - gap);
    const maxHeight = Math.max(1, bottom - gap);
    const visibleHeight = Math.min(height, maxHeight);
    let top = side === 'left' ? anchorTop : anchorBottom + gap;
    if (top + visibleHeight > bottom && anchorTop - gap - visibleHeight >= gap) {
      top = anchorTop - gap - visibleHeight;
    }
    top = Math.max(gap, Math.min(top, bottom - visibleHeight));
    return {top, maxHeight};
  }
  // Measure the actual rendered text; widen only when the available height needs it.
  placePopover.fitWidth = function ({viewportWidth, maxHeight, measure}) {
    const maximum = Math.max(1, Math.min(640, viewportWidth - 28));
    let width = Math.min(380, maximum);
    let height = measure(width);
    while (height > maxHeight && width < maximum) {
      width = Math.min(maximum, width + 40);
      height = measure(width);
    }
    return {width, height};
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = placePopover;
  else root.placeTourPopover = placePopover;
})(typeof window !== 'undefined' ? window : globalThis);
