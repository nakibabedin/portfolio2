// Resizes an image in the browser before upload, re-encoding it as JPEG.
// forceSquare center-crops it first.
export const compressImageFile = (file: File, options?: { maxWidth?: number; maxHeight?: number; quality?: number; forceSquare?: boolean }): Promise<File> => {
  const { maxWidth = 1000, maxHeight = 1000, quality = 0.7, forceSquare = false } = options || {};

  return new Promise((resolve, reject) => {
    const image = new Image();
    const objectUrl = URL.createObjectURL(file);
    image.onload = () => {
      const { width, height } = image;
      let sx = 0;
      let sy = 0;
      let drawWidth = width;
      let drawHeight = height;

      if (forceSquare) {
        const size = Math.min(width, height);
        sx = Math.floor((width - size) / 2);
        sy = Math.floor((height - size) / 2);
        drawWidth = size;
        drawHeight = size;
      }

      const scale = Math.min(maxWidth / drawWidth, maxHeight / drawHeight, 1);
      const targetWidth = Math.round(drawWidth * scale);
      const targetHeight = Math.round(drawHeight * scale);

      const canvas = document.createElement('canvas');
      canvas.width = targetWidth;
      canvas.height = targetHeight;
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        URL.revokeObjectURL(objectUrl);
        reject(new Error('Failed to get canvas context'));
        return;
      }

      ctx.drawImage(image, sx, sy, drawWidth, drawHeight, 0, 0, targetWidth, targetHeight);

      canvas.toBlob((blob) => {
        URL.revokeObjectURL(objectUrl);
        if (!blob) {
          reject(new Error('Failed to generate thumbnail blob'));
          return;
        }
        const thumbnailName = `${file.name.replace(/\.[^/.]+$/, '')}-thumb.jpg`;
        const thumbnailFile = new File([blob], thumbnailName, { type: 'image/jpeg' });
        resolve(thumbnailFile);
      }, 'image/jpeg', quality);
    };
    image.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error('Failed to load image for compression'));
    };
    image.src = objectUrl;
  });
};
