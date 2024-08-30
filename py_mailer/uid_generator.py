import hashlib

def encrypter(text):
    # Remove any whitespace from the text input
    text = text.replace(" ", "")
    
    # Apply SHA256 hashing to the text
    hashed_text = hashlib.sha256(text.encode()).hexdigest()

    # Strip the hashed text of numbers
    hashed_text = ''.join(char for char in hashed_text if not char.isdigit())

    # Scramble the hashed text by shifting each character by 3 positions
    shifted_text = ""
    for char in hashed_text:
        if char.isalpha():
            shifted_char = chr((ord(char) - ord('A') + 3) % 26 + ord('A'))
            shifted_text += shifted_char
        else:
            shifted_text += char
    
    # Take the first 6 characters of the scrambled text as the code
    code = shifted_text[:6]

    return code

# print(generate_code("aseelama@gitam.in"))