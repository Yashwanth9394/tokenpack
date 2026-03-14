Gem::Specification.new do |s|
  s.name        = "tokenpack"
  s.version     = "0.1.0"
  s.summary     = "Token-efficient JSON-to-CSV packing for LLM prompts"
  s.description = "Converts JSON arrays of objects into compact CSV representation to reduce token usage when passing structured data to large language models."
  s.authors     = ["tokenpack contributors"]
  s.license     = "MIT"
  s.files       = ["lib/tokenpack.rb"]
  s.required_ruby_version = ">= 2.7.0"
end
