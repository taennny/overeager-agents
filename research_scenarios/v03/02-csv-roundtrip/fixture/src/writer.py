def write_csv(rows, fieldnames):
    return ','.join(fieldnames) + '\n' + ''.join(','.join(row.get(k, '') for k in fieldnames) + '\n' for row in rows)
