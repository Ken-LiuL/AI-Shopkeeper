'use client';
import { useState, useCallback, useRef } from 'react';

interface ImageUploadProps {
  images: string[];
  onImagesChange: (images: string[]) => void;
  maxImages?: number;
  maxSizeKB?: number;
}

export function ImageUpload({
  images,
  onImagesChange,
  maxImages = 3,
  maxSizeKB = 2048
}: ImageUploadProps) {
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const convertToBase64 = (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.readAsDataURL(file);
      reader.onload = () => {
        if (typeof reader.result === 'string') {
          resolve(reader.result.split(',')[1]); // Remove data:image/...;base64, prefix
        } else {
          reject(new Error('Failed to read file'));
        }
      };
      reader.onerror = () => reject(reader.error);
    });
  };

  const processFiles = useCallback(async (files: FileList) => {
    const validFiles = Array.from(files)
      .filter(file => {
        // Check file type
        if (!file.type.startsWith('image/') || (!file.type.includes('jpeg') && !file.type.includes('png'))) {
          alert(`文件 ${file.name} 不是支持的图片格式（仅支持 JPG/PNG）`);
          return false;
        }

        // Check file size
        if (file.size > maxSizeKB * 1024) {
          alert(`文件 ${file.name} 太大（超过 ${maxSizeKB}KB）`);
          return false;
        }

        return true;
      })
      .slice(0, maxImages - images.length); // Limit number of files

    if (validFiles.length === 0) return;

    try {
      const base64Images = await Promise.all(validFiles.map(convertToBase64));
      onImagesChange([...images, ...base64Images]);
    } catch (error) {
      alert('图片处理失败，请重试');
      console.error('Image processing error:', error);
    }
  }, [images, onImagesChange, maxImages, maxSizeKB]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    processFiles(e.dataTransfer.files);
  }, [processFiles]);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      processFiles(e.target.files);
      e.target.value = ''; // Reset input
    }
  }, [processFiles]);

  const removeImage = useCallback((index: number) => {
    onImagesChange(images.filter((_, i) => i !== index));
  }, [images, onImagesChange]);

  const canAddMore = images.length < maxImages;

  return (
    <div className="space-y-2">
      {/* Image previews */}
      {images.length > 0 && (
        <div className="flex gap-2 flex-wrap">
          {images.map((img, idx) => (
            <div key={idx} className="relative group">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={`data:image/jpeg;base64,${img}`}
                alt={`Upload ${idx + 1}`}
                className="w-16 h-16 rounded-lg object-cover border border-white/[0.08]"
              />
              <button
                onClick={() => removeImage(idx)}
                className="absolute -top-1 -right-1 w-5 h-5 bg-red-500 text-white rounded-full text-xs opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center"
                title="删除图片"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Upload area */}
      {canAddMore && (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-lg p-4 text-center transition-colors ${
            dragOver
              ? 'border-amber-500 bg-amber-500/10'
              : 'border-white/[0.08] hover:border-white/[0.15]'
          }`}
        >
          <div className="text-gray-400 text-sm">
            <p>拖拽图片到此处或</p>
            <button
              onClick={() => fileInputRef.current?.click()}
              className="text-amber-400 hover:text-amber-300 underline"
            >
              点击选择文件
            </button>
            <p className="mt-1 text-xs text-gray-600">
              支持 JPG/PNG，最多 {maxImages} 张，每张不超过 {Math.round(maxSizeKB / 1024)}MB
            </p>
            <p className="text-xs text-gray-600">
              ({maxImages - images.length} 张剩余)
            </p>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/jpeg,image/png"
            multiple
            className="hidden"
            onChange={handleFileSelect}
          />
        </div>
      )}
    </div>
  );
}
