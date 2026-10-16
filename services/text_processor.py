# -*- coding: utf-8 -*-
import re

class TextProcessor:
    """Handles text cleaning and smart segmentation for Spanish content."""
    
    @staticmethod
    def remove_punctuation(text):
        """Removes all punctuation marks (both English/Spanish and Chinese) from text."""
        if not text:
            return ""
        cleaned = re.sub(r'[^\w\s]', ' ', text)
        cleaned = cleaned.replace('_', ' ')
        return re.sub(r'\s+', ' ', cleaned).strip()

    @staticmethod
    def clean_text(text):
        """Cleans input text according to user rules:
        - Replaces newlines/CR with spaces (does not split on newlines)
        - Removes all emojis and symbols (like '👉', '📖', '✨')
        - Removes double quotes (", “, ”)
        - Converts emoji numbers (e.g. 3️⃣) to normal numbers
        """
        if not text:
            return ""
            
        # 0. Replace newlines and carriage returns with spaces
        text = text.replace('\r', ' ').replace('\n', ' ')
            
        # 1. Replace emoji numbers (like 3️⃣) with normal numbers
        # Match digit followed by optional variation selector U+FE0F and enclosing keycap U+20E3
        text = re.sub(r'(\d)\uFE0F?\u20E3', r'\1', text)
        
        # 2. Remove all other emojis and icons:
        # - Characters with code point > 0xFFFF (covers almost all modern emojis like 👉, 📖)
        # - Characters in the Miscellaneous Symbols block (0x2600-0x26FF) and Dingbats (0x2700-0x27BF)
        cleaned_chars = []
        for c in text:
            code = ord(c)
            if 0x2600 <= code <= 0x27BF or code > 0xFFFF:
                continue
            cleaned_chars.append(c)
        text = "".join(cleaned_chars)
        
        # 3. Remove quotes (double quotes, smart quotes)
        text = text.replace('"', '').replace('“', '').replace('”', '')
        
        # 4. Replace colons and parentheses (both English and Chinese) with a space
        for char in (':', '：', '(', ')', '（', '）'):
            text = text.replace(char, ' ')
            
        # 5. Remove spaces before punctuation (e.g. "13 ." -> "13.")
        text = re.sub(r' +([.,?!;])', r'\1', text)
            
        # 6. Clean up spacing
        text = re.sub(r' +', ' ', text)
        
        return text.strip()

    @staticmethod
    def _split_long_chunk(chunk, max_len=170):
        """Splits a single chunk that is longer than max_len into sub-chunks.
        Tries to split by comma first, then by space (words).
        """
        if len(chunk) <= max_len:
            return [chunk]
            
        parts = chunk.split(', ')
        sub_chunks = []
        current = ""
        
        for i, p in enumerate(parts):
            # Append comma back if it's not the last element
            item = p + "," if i < len(parts) - 1 else p
            test = (current + " " + item).strip() if current else item
            
            if len(test) <= max_len:
                current = test
            else:
                if current:
                    sub_chunks.append(current)
                
                # If a single item is still > max_len, split by space (words)
                if len(item) > max_len:
                    words = item.split(' ')
                    word_current = ""
                    for w in words:
                        if not w:
                            continue
                        test_w = (word_current + " " + w).strip() if word_current else w
                        if len(test_w) <= max_len:
                            word_current = test_w
                        else:
                            if word_current:
                                sub_chunks.append(word_current)
                            word_current = w
                    current = word_current
                else:
                    current = item
                    
        if current:
            sub_chunks.append(current)
            
        return sub_chunks

    @staticmethod
    def segment_spanish_text(text, config_manager=None):
        """Segments cleaned Spanish text prioritizing max characters limit per chunk.
        Supports forced split markers (e.g. '///', '|||', '$$') to enforce hard sentence breaks.
        """
        if not text:
            return []
            
        max_limit = config_manager.get_max_chars() if config_manager else 170
        custom_marker = getattr(config_manager, "forced_split_marker", "///") if config_manager else "///"
        
        # Build forced split markers pattern
        markers = [custom_marker, "///", "|||", "$$", "###", "[split]", "[断句]"]
        unique_markers = list(dict.fromkeys([m for m in markers if m]))
        pattern_str = '|'.join(re.escape(m) for m in unique_markers)
        
        # Pre-split text into isolated blocks by forced split markers
        forced_blocks = re.split(pattern_str, text)
        
        results = []
        for block in forced_blocks:
            cleaned_block = TextProcessor.clean_text(block)
            if not cleaned_block:
                continue
            # Process each forced block independently so no greedy merging occurs across markers
            block_results = TextProcessor._segment_single_block(cleaned_block, max_limit, config_manager)
            results.extend(block_results)
            
        return results

    @staticmethod
    def _segment_single_block(cleaned_text, max_limit, config_manager=None):
        """Segments a single forced block using sentence boundaries and greedy merging up to max_limit."""
        initial_chunks = []
        # Split by sentence-ending punctuation (., ?, !, ;) but keep punctuation for initial splitting.
        pattern = re.compile(r'([^.!?;]+[.!?;\s]*)')
        matches = pattern.findall(cleaned_text)
        
        for m in matches:
            trimmed = TextProcessor.remove_punctuation(m)
            if trimmed:
                initial_chunks.append(trimmed)

        # Stage 1: Enforce hard limit on raw chunks by pre-splitting anything > max_limit characters
        raw_chunks = []
        for chunk in initial_chunks:
            if len(chunk) > max_limit:
                raw_chunks.extend(TextProcessor._split_long_chunk(chunk, max_len=max_limit))
            else:
                raw_chunks.append(chunk)

        # Stage 2: Greedy Merging up to max_limit characters
        segments = []
        current_segment = ""
        
        for chunk in raw_chunks:
            test_segment = (current_segment + " " + chunk).strip() if current_segment else chunk
            if len(test_segment) <= max_limit:
                current_segment = test_segment
            else:
                if current_segment:
                    segments.append(TextProcessor.remove_punctuation(current_segment))
                current_segment = chunk

        if current_segment:
            segments.append(TextProcessor.remove_punctuation(current_segment))
        
        # Stage 3: Enforce minimum segment character count
        # If min_segment_chars > 0, merge any segment shorter than the minimum into its neighbor.
        # When simple 2-way merging would exceed max_limit, try combining 3+ neighboring
        # segments and re-splitting them by word boundaries to produce balanced segments.
        min_chars = getattr(config_manager, "min_segment_chars", 0) if config_manager else 0
        if min_chars > 0 and len(segments) > 1:
            merged = True
            while merged:
                merged = False
                i = 0
                while i < len(segments):
                    seg_text = TextProcessor.remove_punctuation(segments[i])
                    if len(seg_text) < min_chars and len(segments) > 1:
                        # Strategy 1: Simple merge with next segment (if fits within max_limit)
                        if i + 1 < len(segments):
                            combined = (segments[i] + " " + segments[i + 1]).strip()
                            combined = TextProcessor.remove_punctuation(combined)
                            if len(combined) <= max_limit:
                                segments[i] = combined
                                segments.pop(i + 1)
                                merged = True
                                continue
                        # Strategy 2: Simple merge with previous segment (if fits within max_limit)
                        if i > 0:
                            combined = (segments[i - 1] + " " + segments[i]).strip()
                            combined = TextProcessor.remove_punctuation(combined)
                            if len(combined) <= max_limit:
                                segments[i - 1] = combined
                                segments.pop(i)
                                merged = True
                                continue
                        # Strategy 3: Multi-segment redistribution
                        # When simple merge exceeds max_limit, combine multiple neighboring
                        # segments and re-split by word boundaries to produce balanced segments
                        # that all meet min_chars.
                        ranges_to_try = []
                        n = len(segments)
                        # 2-segment combinations (re-split into balanced parts)
                        if i > 0:
                            ranges_to_try.append((i - 1, i + 1))
                        if i + 1 < n:
                            ranges_to_try.append((i, i + 2))
                        # 3-segment combinations
                        if i > 0 and i + 1 < n:
                            ranges_to_try.append((i - 1, i + 2))
                        if i > 1:
                            ranges_to_try.append((i - 2, i + 1))
                        if i + 2 < n:
                            ranges_to_try.append((i, i + 3))
                        # 4-segment combinations (fallback for extreme cases)
                        if i > 1 and i + 1 < n:
                            ranges_to_try.append((i - 2, i + 2))
                        if i > 0 and i + 2 < n:
                            ranges_to_try.append((i - 1, i + 3))

                        redistributed = False
                        for start_idx, end_idx in ranges_to_try:
                            range_segs = segments[start_idx:end_idx]
                            combined_text = " ".join(range_segs).strip()
                            combined_text = TextProcessor.remove_punctuation(combined_text)

                            # Re-split combined text by word boundaries using greedy algorithm
                            words = combined_text.split()
                            new_segs = []
                            current = ""
                            for word in words:
                                test = (current + " " + word).strip() if current else word
                                if len(test) <= max_limit:
                                    current = test
                                else:
                                    if current:
                                        new_segs.append(current)
                                    current = word
                            if current:
                                new_segs.append(current)

                            # Accept only if ALL new segments meet min_chars
                            if new_segs and all(len(s) >= min_chars for s in new_segs):
                                segments[start_idx:end_idx] = new_segs
                                redistributed = True
                                merged = True
                                break

                        if redistributed:
                            continue
                        # If no redistribution worked, leave segment as-is
                    i += 1

        # Assign durations
        block_results = []
        for seg in segments:
            seg_text = TextProcessor.remove_punctuation(seg)
            if not seg_text:
                continue
            length = len(seg_text)
            
            if config_manager:
                duration_val = config_manager.get_duration_for_length(length)
            else:
                if length <= 40:
                    duration_val = 4
                elif length <= 90:
                    duration_val = 6
                elif length <= 130:
                    duration_val = 8
                else:
                    duration_val = 10
                
            block_results.append({
                "text": seg_text,
                "length": length,
                "duration": duration_val
            })
            
        return block_results

