# Hybrid card detection

Card Detection uses local image contours first, with an image-AI fallback for sparse or uncertain results. The fallback adds cost and latency, but improves detection of perspective-distorted or low-contrast cards while retaining local processing for straightforward photos.
