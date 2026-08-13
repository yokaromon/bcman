# Best-effort multi-card recognition

Photos queue every detected Business Card without a card-count rejection; eight cards is the quality target, while larger sets continue as best-effort work. Recognition runs through a three-card concurrent queue so completed candidates are available for review immediately, failures remain independently retryable, and long-running sets report their completed-card count.
