require "json"
require "csv"

module PromptPack
  module_function

  # Pack a Ruby hash/array or JSON string into a compact representation.
  # Arrays of hashes become CSV; everything else falls back to compact JSON.
  def pack(data)
    data = JSON.parse(data) if data.is_a?(String)

    if data.is_a?(Array) && is_packable_array?(data)
      array_to_csv(data)
    else
      JSON.generate(data)
    end
  end

  # Unpack a CSV or JSON string back into a Ruby array of hashes.
  def unpack(text)
    text = text.strip
    # Try CSV first if it looks like CSV (starts with a header row, not [ or {)
    if text.start_with?("[") || text.start_with?("{")
      JSON.parse(text)
    else
      csv_to_array(text)
    end
  end

  # Combine a user message with packed data into a single prompt string.
  def pack_for_prompt(message, data)
    packed = pack(data)
    "#{message}\n\n#{packed}"
  end

  # --- internal helpers ---

  # Determine if an array is packable as CSV.
  def is_packable_array?(arr)
    return false unless arr.is_a?(Array) && arr.length >= 2
    return false unless arr.all? { |item| item.is_a?(Hash) }

    all_keys = arr.map { |h| flatten_hash(h).keys.to_set }
    superset = all_keys.reduce(:union)
    shared = all_keys.reduce(:intersection)

    return false if shared.empty?

    arr.each_with_index do |_, i|
      ratio = all_keys[i].length.to_f / superset.length
      return false if ratio < 0.3
    end

    true
  end

  # Flatten a nested hash using dot notation.
  # { "address" => { "city" => "NYC" } } => { "address.city" => "NYC" }
  def flatten_hash(hash, prefix = nil)
    result = {}
    hash.each do |key, value|
      full_key = prefix ? "#{prefix}.#{key}" : key.to_s
      if value.is_a?(Hash)
        result.merge!(flatten_hash(value, full_key))
      else
        result[full_key] = value
      end
    end
    result
  end

  # Convert a value to a CSV cell string.
  def format_cell(value)
    case value
    when nil
      ""
    when Array
      value.map(&:to_s).join("|")
    when true, false
      value.to_s
    else
      value.to_s
    end
  end

  # Convert an array of hashes to a CSV string.
  def array_to_csv(arr)
    flat_rows = arr.map { |h| flatten_hash(h) }
    # Collect all keys in stable order (insertion order from first appearance)
    seen = {}
    flat_rows.each do |row|
      row.each_key { |k| seen[k] = true unless seen.key?(k) }
    end
    headers = seen.keys

    CSV.generate(row_sep: "\n") do |csv|
      csv << headers
      flat_rows.each do |row|
        csv << headers.map { |h| format_cell(row[h]) }
      end
    end
  end

  # Parse a single CSV cell back into a Ruby value.
  def parse_cell(cell)
    return nil if cell.nil? || cell == ""
    return true if cell == "true"
    return false if cell == "false"
    return cell.to_i if cell =~ /\A-?\d+\z/
    return cell.to_f if cell =~ /\A-?\d+\.\d+\z/
    return cell.split("|") if cell.include?("|")
    cell
  end

  # Unflatten dot-notation keys back into nested hashes.
  # { "address.city" => "NYC" } => { "address" => { "city" => "NYC" } }
  def unflatten_hash(flat)
    result = {}
    flat.each do |key, value|
      parts = key.split(".")
      current = result
      parts[0..-2].each do |part|
        current[part] ||= {}
        current = current[part]
      end
      current[parts.last] = value
    end
    result
  end

  # Convert a CSV string back into an array of hashes.
  def csv_to_array(text)
    rows = CSV.parse(text)
    return [] if rows.empty?

    headers = rows[0]
    rows[1..].map do |row|
      flat = {}
      headers.each_with_index do |header, i|
        flat[header] = parse_cell(row[i])
      end
      unflatten_hash(flat)
    end
  end

  private_class_method :is_packable_array?, :flatten_hash, :format_cell,
                       :array_to_csv, :parse_cell, :unflatten_hash,
                       :csv_to_array
end
