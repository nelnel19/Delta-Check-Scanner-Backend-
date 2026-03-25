# extractor.py
import re
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

def extract_fields(text):
    if not text:
        return {
            "account_no": None,
            "account_name": None,
            "pay_to_the_order_of": None,
            "check_no": None,
            "amount": None,
            "bank_name": None,
            "date": None
        }
    
    original_text = text
    text = text.replace('\n', ' ').replace('\r', ' ')
    text = re.sub(r'\s+', ' ', text)
    
    lines = [line.strip() for line in original_text.split('\n') if line.strip()]
    
    result = {}
    result["bank_name"] = extract_bank_name(lines)
    result["account_name"] = extract_account_name(lines, original_text)
    result["account_no"] = extract_account_number(lines, original_text, text)
    result["check_no"] = extract_check_number(lines, original_text, text)
    result["pay_to_the_order_of"] = extract_payee(lines, original_text)
    result["amount"] = extract_amount(lines, original_text)
    result["date"] = extract_date(lines, original_text, text)
    
    return result


def extract_bank_name(lines):
    for line in lines:
        line_upper = line.upper()
        if "SECURITY BANK" in line_upper:
            return "SECURITY BANK"
        elif "BANK OF THE PHILIPPINE ISLANDS" in line_upper:
            return "BANK OF THE PHILIPPINE ISLANDS (BPI)"
        elif "BPI" in line_upper and "BANK" in line_upper:
            return "BANK OF THE PHILIPPINE ISLANDS (BPI)"
        elif "BDO" in line_upper:
            return "BDO UNIBANK"
        elif "METROBANK" in line_upper or "METROPOLITAN BANK" in line_upper:
            return "METROPOLITAN BANK"
        elif "PNB" in line_upper or "PHILIPPINE NATIONAL BANK" in line_upper:
            return "PHILIPPINE NATIONAL BANK"
        elif "BANK" in line_upper and len(line) < 50:
            clean = re.sub(r'\s+', ' ', line).strip()
            if 3 < len(clean) < 50:
                return clean
    return None


def extract_account_name(lines, original_text):
    text_lines = original_text.split('\n')
    account_name_candidates = []
    
    for i, line in enumerate(text_lines):
        if "ACCOUNT NAME" in line.upper():
            logger.debug(f"Found ACCOUNT NAME at line {i}")
            parts = re.split(r'ACCOUNT\s+NAME\s*[:.]?\s*', line, flags=re.IGNORECASE)
            if len(parts) > 1 and parts[1].strip():
                candidate = clean_name(parts[1])
                if candidate and len(candidate) > 3:
                    logger.debug(f"Found on same line: {candidate}")
                    return candidate
            if i + 1 < len(text_lines):
                next_line = text_lines[i + 1].strip()
                if next_line and not re.search(r'\d', next_line):
                    candidate = clean_name(next_line)
                    if candidate and len(candidate) > 3:
                        logger.debug(f"Found on next line: {candidate}")
                        return candidate
            if i + 2 < len(text_lines):
                second_line = text_lines[i + 2].strip()
                if second_line and not re.search(r'\d', second_line):
                    candidate = clean_name(second_line)
                    if candidate and len(candidate) > 3:
                        logger.debug(f"Found two lines after: {candidate}")
                        return candidate
    
    for i, line in enumerate(text_lines):
        if "ACCT NAME" in line.upper() or "ACCT. NAME" in line.upper():
            parts = re.split(r'ACCT\.?\s+NAME\s*[:.]?\s*', line, flags=re.IGNORECASE)
            if len(parts) > 1 and parts[1].strip():
                candidate = clean_name(parts[1])
                if candidate and len(candidate) > 3:
                    return candidate
            if i + 1 < len(text_lines):
                next_line = text_lines[i + 1].strip()
                if next_line and not re.search(r'\d', next_line):
                    candidate = clean_name(next_line)
                    if candidate and len(candidate) > 3:
                        return candidate
    
    payee_index = find_payee_line_index(text_lines)
    for i, line in enumerate(text_lines[:payee_index] if payee_index > 0 else text_lines[:5]):
        if re.search(r'(?:INC|CORP|LLC|CO\.|COMPANY|ENTERPRISES|TRADING|SUPPLY|DISTRIBUTOR|SALES|SERVICES|INDUSTRIAL)', line.upper()):
            if "BANK" not in line.upper() and "CHECK" not in line.upper() and "ACCOUNT" not in line.upper():
                candidate = clean_name(line)
                if candidate and len(candidate) > 3:
                    logger.debug(f"Found account name candidate (top section): {candidate}")
                    account_name_candidates.append(candidate)
    
    if account_name_candidates:
        return account_name_candidates[0]
    return None


def extract_account_number(lines, original_text, text):
    all_possible_accounts = []
    
    for line in lines:
        # Pattern for typical Philippine bank account format: 4-4-2 or 3-6-3
        match = re.search(r'(\d{4}-\d{4}-\d{2})', line)
        if match:
            return match.group(1)
        match = re.search(r'(\d{3}-\d{6}-\d{3})', line)
        if match:
            return match.group(1)
        match = re.search(r'(\d{3,4}-\d{3,7}-\d{2,4})', line)
        if match:
            all_possible_accounts.append(match.group(1))
    
    for i, line in enumerate(lines):
        line_upper = line.upper()
        if "ACCOUNT NO" in line_upper or "ACCT NO" in line_upper or "A/C NO" in line_upper:
            number_match = re.search(r'(?:ACCOUNT|ACCT|A/C)\s+NO\.?\s*:?\s*([0-9\-]+)', line, re.IGNORECASE)
            if number_match:
                account_num = number_match.group(1).strip()
                if len(account_num.replace('-', '')) >= 8:
                    return account_num
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                number_match = re.search(r'([0-9\-]{8,20})', next_line)
                if number_match:
                    account_num = number_match.group(1).strip('-')
                    if len(account_num.replace('-', '')) >= 8:
                        return account_num
    
    for line in lines:
        numbers = re.findall(r'\b(\d{10,12})\b', line)
        for num in numbers:
            if not is_check_number(num):
                all_possible_accounts.append(num)
    
    bottom_lines = lines[len(lines)//2:]
    for line in bottom_lines:
        numbers = re.findall(r'([0-9\-]{10,20})', line)
        for num in numbers:
            cleaned = num.replace('-', '')
            if len(cleaned) >= 8 and len(cleaned) <= 16:
                if not is_check_number(cleaned):
                    all_possible_accounts.append(num)
    
    if all_possible_accounts:
        seen = set()
        unique_accounts = []
        for acc in all_possible_accounts:
            if acc not in seen:
                seen.add(acc)
                unique_accounts.append(acc)
        return unique_accounts[0]
    return None


def extract_check_number(lines, original_text, text):
    text_lines = original_text.split('\n')
    
    check_label_patterns = [
        r'CHECK\s+NO\.?\s*:?\s*(\d+)',
        r'CHK\s+NO\.?\s*:?\s*(\d+)',
        r'CHECK\s+#\s*:?\s*(\d+)',
        r'#\s*(\d+)',
        r'NO\.?\s*:?\s*(\d+)',
    ]
    
    for i, line in enumerate(text_lines):
        line_upper = line.upper()
        if "CHECK" in line_upper or "CHK" in line_upper or "#" in line:
            for pattern in check_label_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    check_num = match.group(1)
                    if len(check_num) >= 6 and len(check_num) <= 12:
                        return check_num
    
    for i, line in enumerate(text_lines[:5]):
        numbers = re.findall(r'\b(\d{9,12})\b', line)
        for num in numbers:
            if len(num) >= 9 and len(num) <= 12:
                if not re.match(r'\d{2}[-/]\d{2}[-/]\d{4}', num):
                    return num
    
    for i, line in enumerate(text_lines):
        if "NO." in line.upper() or "#" in line:
            numbers = re.findall(r'\b(\d{9,12})\b', line)
            if numbers:
                return numbers[0]
    
    all_numbers = re.findall(r'\b(\d{9,12})\b', text)
    for num in all_numbers:
        if not re.match(r'\d{2}[-/]\d{2}[-/]\d{4}', num):
            if '-' not in num:
                return num
    return None


def find_payee_line_index(text_lines):
    for i, line in enumerate(text_lines):
        if "PAY TO THE" in line.upper() or "ORDER OF" in line.upper():
            return i
    return len(text_lines) // 2


def extract_payee(lines, original_text):
    text_lines = original_text.split('\n')
    
    logger.debug("="*50)
    logger.debug("PAYEE EXTRACTION DEBUG - ENHANCED")
    logger.debug("="*50)
    for i, line in enumerate(text_lines):
        logger.debug(f"Line {i}: '{line}'")
    
    # METHOD 1: Look for "PAY TO THE" on a line
    for i, line in enumerate(text_lines):
        if "PAY TO THE" in line.upper():
            logger.debug(f"Found PAY TO THE at line {i}: '{line}'")
            payee_parts = []
            
            # Extract text after "PAY TO THE" on the same line
            parts = re.split(r'PAY\s+TO\s+THE\s*', line, flags=re.IGNORECASE)
            if len(parts) > 1 and parts[1].strip():
                first_part = parts[1].strip()
                # Remove any "ORDER OF" that might be on the same line
                first_part = re.sub(r'ORDER\s+OF.*$', '', first_part, flags=re.IGNORECASE).strip()
                if first_part:
                    payee_parts.append(first_part)
                    logger.debug(f"  Found on same line: '{first_part}'")
            
            # Collect subsequent lines until we hit a clear field delimiter
            stop_patterns = [
                r'AMOUNT', r'PESOS', r'DATE', r'ACCOUNT', r'CHECK', r'BRSTN',
                r'BANK', r'SECURITY', r'BDO', r'METRO', r'BPI', r'PNB',
                r'\b\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b'  # any amount-like number
            ]
            for j in range(i + 1, min(i + 10, len(text_lines))):
                next_line = text_lines[j].strip()
                if not next_line:
                    continue
                
                # Skip lines that are just "ORDER OF" (common standalone)
                if re.match(r'^\s*ORDER\s+OF\s*$', next_line, re.IGNORECASE):
                    logger.debug(f"  Skipping standalone ORDER OF line {j}")
                    continue
                
                # Stop if next line matches any delimiter
                if any(re.search(pattern, next_line.upper()) for pattern in stop_patterns):
                    logger.debug(f"  Stopping at line {j} (hit delimiter: '{next_line}')")
                    break
                payee_parts.append(next_line)
                logger.debug(f"  Added line {j}: '{next_line}'")
            
            if payee_parts:
                full_payee = " ".join(payee_parts)
                full_payee = clean_payee(full_payee)
                logger.debug(f"  Full payee: '{full_payee}'")
                if full_payee and len(full_payee) > 3:
                    return full_payee
    
    # METHOD 2: Look for lines between "PAY TO THE" and "ORDER OF"
    pay_to_index = -1
    order_of_index = -1
    
    for i, line in enumerate(text_lines):
        if "PAY TO THE" in line.upper():
            pay_to_index = i
        if "ORDER OF" in line.upper():
            order_of_index = i
    
    if pay_to_index != -1 and order_of_index != -1 and order_of_index > pay_to_index:
        logger.debug(f"Found PAY TO THE at {pay_to_index}, ORDER OF at {order_of_index}")
        payee_lines = []
        for j in range(pay_to_index + 1, order_of_index):
            if text_lines[j].strip():
                # Skip if line is just "ORDER OF"
                if re.match(r'^\s*ORDER\s+OF\s*$', text_lines[j].strip(), re.IGNORECASE):
                    continue
                payee_lines.append(text_lines[j].strip())
                logger.debug(f"  Collected line {j}: '{text_lines[j].strip()}'")
        
        if payee_lines:
            payee = " ".join(payee_lines)
            payee = clean_payee(payee)
            logger.debug(f"  Payee between markers: '{payee}'")
            return payee
    
    # METHOD 3: Look for company name patterns near payee context
    for i, line in enumerate(text_lines):
        if re.search(r'[A-Z]{4,}.*(?:,?\s*(?:INC|CORP|LLC|CO\.|COMPANY|ENTERPRISES|TRADING|SUPPLY|DISTRIBUTOR|SALES|SERVICES))', line.upper()):
            context_before = ' '.join(text_lines[max(0, i-3):i]).upper()
            context_after = ' '.join(text_lines[i:min(len(text_lines), i+3)]).upper()
            if "PAY" in context_before or "ORDER" in context_before or "PAY" in context_after:
                payee = clean_payee(line)
                logger.debug(f"  Found payee by context: '{payee}'")
                if payee and len(payee) > 3:
                    return payee
    
    # METHOD 4: Look specifically for pattern with comma
    for i, line in enumerate(text_lines):
        match = re.search(r'([A-Z\s]+,\s*(?:INC|CORP|LLC)\.?)', line.upper())
        if match:
            potential_payee = match.group(1)
            context = ' '.join(text_lines[max(0, i-2):min(len(text_lines), i+3)]).upper()
            if "PAY" in context or "ORDER" in context:
                payee = clean_payee(potential_payee)
                logger.debug(f"  Found payee with comma pattern: '{payee}'")
                return payee
    
    logger.debug("No payee found")
    return None


def extract_amount(lines, original_text):
    # First try standard numeric patterns
    for line in lines:
        # Pattern for amount with commas and decimal
        match = re.search(r'([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]{2})?)', line)
        if match:
            amount = match.group(1)
            try:
                num_value = float(amount.replace(',', ''))
                if num_value > 10:
                    return f"₱{amount}"
            except:
                continue
        
        # Pattern for amount without commas but with decimal
        match = re.search(r'([0-9]+\.\d{2})', line)
        if match:
            amount = match.group(1)
            try:
                num_value = float(amount)
                if num_value > 10:
                    parts = amount.split('.')
                    whole = parts[0]
                    if len(whole) > 3:
                        whole = re.sub(r'(?<=\d)(?=(\d{3})+(?!\d))', ',', whole)
                    return f"₱{whole}.{parts[1]}"
            except:
                continue
        
        # Pattern for amount with P prefix (e.g., "P40,237.50" or "P 40,237.50")
        match = re.search(r'P\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})?)', line, re.IGNORECASE)
        if match:
            amount = match.group(1)
            try:
                num_value = float(amount.replace(',', ''))
                if num_value > 10:
                    return f"₱{amount}"
            except:
                continue
    
    # If still not found, look for amounts in the whole text near "AMOUNT" or "PESOS"
    full_text = original_text.replace('\n', ' ').upper()
    if "AMOUNT" in full_text or "PESOS" in full_text:
        # Find the line that contains "AMOUNT" and try to extract number after it
        for line in lines:
            if "AMOUNT" in line.upper() or "PESOS" in line.upper():
                match = re.search(r'(?:AMOUNT|PESOS)\s*:?\s*([0-9,]+(?:\.[0-9]{2})?)', line, re.IGNORECASE)
                if match:
                    amount = match.group(1)
                    try:
                        num_value = float(amount.replace(',', ''))
                        if num_value > 10:
                            return f"₱{amount}"
                    except:
                        continue
                # Also look on next line
                idx = lines.index(line)
                if idx + 1 < len(lines):
                    next_line = lines[idx+1]
                    match = re.search(r'([0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]{2})?)', next_line)
                    if match:
                        amount = match.group(1)
                        try:
                            num_value = float(amount.replace(',', ''))
                            if num_value > 10:
                                return f"₱{amount}"
                        except:
                            continue
    
    return None


def extract_date(lines, original_text, text):
    logger.debug("="*50)
    logger.debug("DATE EXTRACTION DEBUG - ENHANCED")
    logger.debug("="*50)
    
    text_lines = original_text.split('\n')
    for i, line in enumerate(text_lines):
        logger.debug(f"Line {i}: '{line}'")
    
    # Expanded patterns: include underscore separator, also handle month names
    date_patterns = [
        r'DATE\s*:?\s*(\d{1,2})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{4})',
        r'DATE\s+(\d{1,2})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{4})',
        r'DATE(\d{2})\s*[-/]\s*(\d{2})\s*[-/]\s*(\d{4})',
        r'DATE\s*:?\s*(\d{1,2})\s+(\d{1,2})\s+(\d{4})',
        r'(\d{2})\s*[-/]\s*(\d{2})\s*[-/]\s*(\d{4})',
        r'(\d{2})\s+(\d{2})\s+(\d{4})',
        r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})',
        r'(\d{2})_(\d{2})_(\d{4})',                 # underscore separator
    ]
    
    # Month name patterns
    month_map = {
        'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04',
        'MAY': '05', 'JUN': '06', 'JUL': '07', 'AUG': '08',
        'SEP': '09', 'OCT': '10', 'NOV': '11', 'DEC': '12'
    }
    
    # METHOD 1: Look for lines with "DATE" label
    for i, line in enumerate(text_lines):
        line_upper = line.upper()
        if 'DATE' in line_upper:
            logger.debug(f"Found DATE reference in line {i}")
            for pattern in date_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match and len(match.groups()) == 3:
                    month, day, year = match.groups()
                    month = re.sub(r'\D', '', month).zfill(2)
                    day = re.sub(r'\D', '', day).zfill(2)
                    year = re.sub(r'\D', '', year)
                    if len(year) == 2:
                        year = f"20{year}"
                    logger.debug(f"  Found date: {month}-{day}-{year}")
                    if is_valid_date(month, day, year):
                        logger.debug(f"  ✓ VALID DATE FOUND!")
                        return f"{month}-{day}-{year}"
            
            # Also look for month name patterns
            month_match = re.search(r'DATE\s*:?\s*([A-Za-z]{3,})\s+(\d{1,2}),?\s+(\d{4})', line, re.IGNORECASE)
            if month_match:
                month_name, day, year = month_match.groups()
                month = month_map.get(month_name.upper()[:3], None)
                if month and is_valid_date(month, day, year):
                    return f"{month}-{day.zfill(2)}-{year}"
            
            if i + 1 < len(text_lines):
                next_line = text_lines[i + 1]
                logger.debug(f"  Checking next line: '{next_line}'")
                for pattern in date_patterns:
                    match = re.search(pattern, next_line, re.IGNORECASE)
                    if match and len(match.groups()) == 3:
                        month, day, year = match.groups()
                        month = re.sub(r'\D', '', month).zfill(2)
                        day = re.sub(r'\D', '', day).zfill(2)
                        year = re.sub(r'\D', '', year)
                        if len(year) == 2:
                            year = f"20{year}"
                        logger.debug(f"  Found date in next line: {month}-{day}-{year}")
                        if is_valid_date(month, day, year):
                            return f"{month}-{day}-{year}"
                
                # Also month name in next line
                month_match = re.search(r'([A-Za-z]{3,})\s+(\d{1,2}),?\s+(\d{4})', next_line, re.IGNORECASE)
                if month_match:
                    month_name, day, year = month_match.groups()
                    month = month_map.get(month_name.upper()[:3], None)
                    if month and is_valid_date(month, day, year):
                        return f"{month}-{day.zfill(2)}-{year}"
    
    # METHOD 2: Look for any date pattern without label
    for i, line in enumerate(text_lines):
        for pattern in date_patterns:
            match = re.search(pattern, line, re.IGNORECASE)
            if match and len(match.groups()) == 3:
                month, day, year = match.groups()
                month = re.sub(r'\D', '', month).zfill(2)
                day = re.sub(r'\D', '', day).zfill(2)
                year = re.sub(r'\D', '', year)
                if len(year) == 2:
                    year = f"20{year}"
                logger.debug(f"Found date in line {i}: {month}-{day}-{year}")
                if is_valid_date(month, day, year):
                    return f"{month}-{day}-{year}"
        
        # Look for month name patterns without DATE label
        month_match = re.search(r'([A-Za-z]{3,})\s+(\d{1,2}),?\s+(\d{4})', line, re.IGNORECASE)
        if month_match:
            month_name, day, year = month_match.groups()
            month = month_map.get(month_name.upper()[:3], None)
            if month and is_valid_date(month, day, year):
                return f"{month}-{day.zfill(2)}-{year}"
    
    # METHOD 3: Handle theta (θ) characters
    for i, line in enumerate(text_lines):
        if 'θ' in line or 'Θ' in line or '0' in line:
            converted = line.replace('θ', '0').replace('Θ', '0')
            for pattern in date_patterns:
                match = re.search(pattern, converted, re.IGNORECASE)
                if match and len(match.groups()) == 3:
                    month, day, year = match.groups()
                    month = re.sub(r'\D', '', month).zfill(2)
                    day = re.sub(r'\D', '', day).zfill(2)
                    year = re.sub(r'\D', '', year)
                    if len(year) == 2:
                        year = f"20{year}"
                    logger.debug(f"Found date with theta conversion: {month}-{day}-{year}")
                    if is_valid_date(month, day, year):
                        return f"{month}-{day}-{year}"
    
    # METHOD 4: Look for MMDDYYYY box indicators
    for i, line in enumerate(text_lines):
        if 'M' in line.upper() and 'D' in line.upper() and 'Y' in line.upper():
            logger.debug(f"Found MMDDYYYY indicator at line {i}")
            if i > 0:
                prev_line = text_lines[i - 1]
                digits = re.findall(r'\d', prev_line)
                if len(digits) >= 8:
                    date_str = ''.join(digits[:8])
                    month = date_str[0:2]
                    day = date_str[2:4]
                    year = date_str[4:8]
                    logger.debug(f"  Found digits: {month}-{day}-{year}")
                    if is_valid_date(month, day, year):
                        return f"{month}-{day}-{year}"
    
    # METHOD 5: Extract any 8‑digit sequence
    full_text_no_spaces = re.sub(r'\s+', '', original_text)
    logger.debug(f"Full text without spaces: '{full_text_no_spaces}'")
    digit_sequences = re.findall(r'\d{8,}', full_text_no_spaces)
    for seq in digit_sequences:
        for j in range(len(seq) - 7):
            potential = seq[j:j+8]
            month = potential[0:2]
            day = potential[2:4]
            year = potential[4:8]
            if is_valid_date(month, day, year):
                logger.debug(f"Found date in full text: {month}-{day}-{year}")
                return f"{month}-{day}-{year}"
    
    # METHOD 6: Look for dates at the top right (often the first few lines)
    for i in range(min(5, len(text_lines))):
        line = text_lines[i]
        # Try to find a pattern like "Mar 15, 2024" or "March 15, 2024"
        month_match = re.search(r'([A-Za-z]{3,})\s+(\d{1,2}),?\s+(\d{4})', line, re.IGNORECASE)
        if month_match:
            month_name, day, year = month_match.groups()
            month = month_map.get(month_name.upper()[:3], None)
            if month and is_valid_date(month, day, year):
                return f"{month}-{day.zfill(2)}-{year}"
        
        # Try numeric pattern at top
        numeric_match = re.search(r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})', line)
        if numeric_match:
            month, day, year = numeric_match.groups()
            month = month.zfill(2)
            day = day.zfill(2)
            if is_valid_date(month, day, year):
                return f"{month}-{day}-{year}"
    
    logger.debug("="*50)
    logger.debug("NO DATE FOUND")
    logger.debug("="*50)
    return None


def is_check_number(num):
    num_str = str(num)
    return (9 <= len(num_str) <= 12)


def is_valid_date(month, day, year):
    try:
        month_int = int(month)
        day_int = int(day)
        year_int = int(year)
        
        if not (1 <= month_int <= 12):
            return False
        if not (1 <= day_int <= 31):
            return False
        if not (2000 <= year_int <= 2100):
            return False
        
        if month_int in [4, 6, 9, 11] and day_int > 30:
            return False
        if month_int == 2:
            if day_int > 29:
                return False
            if day_int == 29 and year_int % 4 != 0:
                return False
        
        return True
    except ValueError:
        return False


def clean_name(name):
    name = re.sub(r'\s+', ' ', name).strip()
    name = re.sub(r'[,\s]+$', '', name)
    name = re.sub(r'\s+\d+$', '', name)
    return name if len(name) > 2 else None


def clean_payee(payee):
    """
    Clean extracted payee name while preserving commas and INC/CORP,
    and removing any leading/trailing "ORDER OF" text.
    """
    payee = re.sub(r'\s+', ' ', payee).strip()
    # Remove leading "ORDER OF" (case-insensitive)
    payee = re.sub(r'^(ORDER\s+OF\s*)', '', payee, flags=re.IGNORECASE).strip()
    payee = re.sub(r'[,\s]+$', '', payee)
    payee = re.sub(r'\s+(?:P|₱|PHP|pesos|amount|AMOUNT).*$', '', payee, flags=re.IGNORECASE)
    payee = re.sub(r'\s+\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$', '', payee)
    payee = re.sub(r'\s+\d+[\d,.]*$', '', payee)
    payee = re.sub(r'\s+ORDER\s+OF.*$', '', payee, flags=re.IGNORECASE)  # remove trailing ORDER OF
    if payee.endswith(','):
        payee = payee[:-1].strip()
    return payee if len(payee) > 3 else None


def validate_check_data(data):
    validation = {
        "is_valid": True,
        "warnings": [],
        "missing_fields": [],
        "extracted_fields": {}
    }
    
    for key, value in data.items():
        if value:
            validation["extracted_fields"][key] = "extracted"
        else:
            validation["extracted_fields"][key] = "missing"
            validation["missing_fields"].append(key.replace('_', ' ').title())
    
    if validation["missing_fields"]:
        validation["is_valid"] = False
        validation["warnings"].append(f"Missing fields: {', '.join(validation['missing_fields'])}")
    
    return validation