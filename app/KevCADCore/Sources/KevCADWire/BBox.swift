import Foundation
import simd

/// Hüllquader in Weltkoordinaten (mm), wie `bbox` in PART_UPSERT und in den Teilen des Spiegels.
public struct BBox: Codable, Equatable, Sendable {
    public var min: [Double]
    public var max: [Double]

    public init(min: [Double], max: [Double]) {
        self.min = min
        self.max = max
    }

    public var minVector: SIMD3<Float>? {
        min.count >= 3 ? SIMD3(Float(min[0]), Float(min[1]), Float(min[2])) : nil
    }

    public var maxVector: SIMD3<Float>? {
        max.count >= 3 ? SIMD3(Float(max[0]), Float(max[1]), Float(max[2])) : nil
    }
}
