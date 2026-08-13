# Normalize image-AI detection coordinates

Image-AI Card Detection returns corners as fractions of the Photo dimensions, which the server converts to source-image pixels before deduplication or cropping. Invalid fractions are discarded rather than guessed, preventing resized AI input from producing duplicate or incorrectly cropped Business Cards.
