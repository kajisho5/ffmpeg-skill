### Changed

- The social card (`brand/og.png`, `site/brand/og.png`) is drawn by `brand/og.py` with the tool count read from the contract and records the line it shows; a test fails when that line, or README's alt text for the card, is not the contract's count, so a change of the count redraws the card.
