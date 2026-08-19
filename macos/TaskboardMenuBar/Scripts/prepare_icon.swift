#!/usr/bin/env swift

import CoreGraphics
import Foundation
import ImageIO
import UniformTypeIdentifiers

enum IconPreparationError: LocalizedError {
    case usage
    case cannotRead(String)
    case cannotCreateContext
    case cannotWrite(String)

    var errorDescription: String? {
        switch self {
        case .usage:
            return "用法: prepare_icon.swift <input.png> <output.png>"
        case let .cannotRead(path):
            return "无法读取图片: \(path)"
        case .cannotCreateContext:
            return "无法创建 CoreGraphics 位图上下文"
        case let .cannotWrite(path):
            return "无法写入 PNG: \(path)"
        }
    }
}

func loadImage(at url: URL) throws -> CGImage {
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        throw IconPreparationError.cannotRead(url.path)
    }
    return image
}

func makeContext(
    data: UnsafeMutableRawPointer?,
    width: Int,
    height: Int,
    bytesPerRow: Int
) throws -> CGContext {
    let bitmapInfo = CGBitmapInfo.byteOrder32Big.rawValue
        | CGImageAlphaInfo.premultipliedLast.rawValue
    guard let context = CGContext(
        data: data,
        width: width,
        height: height,
        bitsPerComponent: 8,
        bytesPerRow: bytesPerRow,
        space: CGColorSpaceCreateDeviceRGB(),
        bitmapInfo: bitmapInfo
    ) else {
        throw IconPreparationError.cannotCreateContext
    }
    context.interpolationQuality = .high
    return context
}

func keepLargestAlphaComponent(in pixels: inout [UInt8], width: Int, height: Int) {
    let pixelCount = width * height
    let threshold: UInt8 = 8
    var labels = [Int32](repeating: -1, count: pixelCount)
    var queue = [Int](repeating: 0, count: pixelCount)
    var label: Int32 = 0
    var largestLabel: Int32 = -1
    var largestSize = 0

    func hasAlpha(_ index: Int) -> Bool {
        pixels[index * 4 + 3] > threshold
    }

    for start in 0..<pixelCount where labels[start] == -1 && hasAlpha(start) {
        var head = 0
        var tail = 1
        var componentSize = 0
        queue[0] = start
        labels[start] = label

        while head < tail {
            let index = queue[head]
            head += 1
            componentSize += 1
            let x = index % width
            let y = index / width

            if x > 0 {
                let neighbor = index - 1
                if labels[neighbor] == -1 && hasAlpha(neighbor) {
                    labels[neighbor] = label
                    queue[tail] = neighbor
                    tail += 1
                }
            }
            if x + 1 < width {
                let neighbor = index + 1
                if labels[neighbor] == -1 && hasAlpha(neighbor) {
                    labels[neighbor] = label
                    queue[tail] = neighbor
                    tail += 1
                }
            }
            if y > 0 {
                let neighbor = index - width
                if labels[neighbor] == -1 && hasAlpha(neighbor) {
                    labels[neighbor] = label
                    queue[tail] = neighbor
                    tail += 1
                }
            }
            if y + 1 < height {
                let neighbor = index + width
                if labels[neighbor] == -1 && hasAlpha(neighbor) {
                    labels[neighbor] = label
                    queue[tail] = neighbor
                    tail += 1
                }
            }
        }

        if componentSize > largestSize {
            largestSize = componentSize
            largestLabel = label
        }
        label += 1
    }

    for index in 0..<pixelCount where labels[index] != largestLabel {
        let offset = index * 4
        pixels[offset] = 0
        pixels[offset + 1] = 0
        pixels[offset + 2] = 0
        pixels[offset + 3] = 0
    }
}

func cleanAndResize(_ image: CGImage, outputSize: Int = 1024) throws -> CGImage {
    let width = image.width
    let height = image.height
    let bytesPerRow = width * 4
    var pixels = [UInt8](repeating: 0, count: height * bytesPerRow)

    try pixels.withUnsafeMutableBytes { buffer in
        let context = try makeContext(
            data: buffer.baseAddress,
            width: width,
            height: height,
            bytesPerRow: bytesPerRow
        )
        context.clear(CGRect(x: 0, y: 0, width: width, height: height))
        context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
    }
    keepLargestAlphaComponent(in: &pixels, width: width, height: height)

    let cleaned: CGImage = try pixels.withUnsafeMutableBytes { buffer in
        let context = try makeContext(
            data: buffer.baseAddress,
            width: width,
            height: height,
            bytesPerRow: bytesPerRow
        )
        guard let image = context.makeImage() else {
            throw IconPreparationError.cannotCreateContext
        }
        return image
    }

    let outputBytesPerRow = outputSize * 4
    var outputPixels = [UInt8](repeating: 0, count: outputSize * outputBytesPerRow)
    return try outputPixels.withUnsafeMutableBytes { buffer in
        let context = try makeContext(
            data: buffer.baseAddress,
            width: outputSize,
            height: outputSize,
            bytesPerRow: outputBytesPerRow
        )
        context.clear(CGRect(x: 0, y: 0, width: outputSize, height: outputSize))
        context.draw(
            cleaned,
            in: CGRect(x: 0, y: 0, width: outputSize, height: outputSize)
        )
        guard let resized = context.makeImage() else {
            throw IconPreparationError.cannotCreateContext
        }
        return resized
    }
}

func writePNG(_ image: CGImage, to url: URL) throws {
    guard let destination = CGImageDestinationCreateWithURL(
        url as CFURL,
        UTType.png.identifier as CFString,
        1,
        nil
    ) else {
        throw IconPreparationError.cannotWrite(url.path)
    }
    CGImageDestinationAddImage(destination, image, nil)
    guard CGImageDestinationFinalize(destination) else {
        throw IconPreparationError.cannotWrite(url.path)
    }
}

do {
    guard CommandLine.arguments.count == 3 else {
        throw IconPreparationError.usage
    }
    let inputURL = URL(fileURLWithPath: CommandLine.arguments[1])
    let outputURL = URL(fileURLWithPath: CommandLine.arguments[2])
    let image = try loadImage(at: inputURL)
    let prepared = try cleanAndResize(image)
    try writePNG(prepared, to: outputURL)
    print(outputURL.path)
} catch {
    fputs("\(error.localizedDescription)\n", stderr)
    exit(1)
}
