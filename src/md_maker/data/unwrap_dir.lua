-- Drop dir="rtl"/"ltr" wrappers: they only add tokens to the Markdown.
local function unwrap(el)
  if el.attributes.dir and el.identifier == "" and #el.classes == 0 then
    return el.content
  end
end

return { { Span = unwrap, Div = unwrap } }
