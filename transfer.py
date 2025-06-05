with open('out.txt', 'r') as infile, open('stdout.txt', 'w') as outfile:
    for line in infile:
        if not line.startswith('[Log]'):
            outfile.write(line)