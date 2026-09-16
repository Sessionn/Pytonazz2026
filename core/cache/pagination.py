"""Bounded, deterministic pages over internal read-model SQL."""


def read_page(cur, select: str, *, page=1, page_size=50, search='', sort='id',
              order='desc', source='', valid='') -> dict:
    page = max(1, int(page))
    page_size = max(1, min(200, int(page_size)))
    columns = [item[0] for item in cur.execute(f'SELECT * FROM ({select}) LIMIT 0').description]
    sort = sort if sort in columns else 'id'
    direction = 'DESC' if str(order).lower() == 'desc' else 'ASC'
    filters, params = [], []
    if search:
        fields = ['title', 'artist', 'query_raw'] if 'query_raw' in columns and 'is_valid' in columns else columns
        filters.append('(' + ' OR '.join(f'LOWER(CAST("{col}" AS TEXT)) LIKE ? ESCAPE \'\\\'' for col in fields) + ')')
        escaped = search.lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        params.extend([f'%{escaped}%'] * len(fields))
    if source and 'source' in columns:
        filters.append('source = ?')
        params.append(source)
    if valid in ('0', '1') and 'is_valid' in columns:
        filters.append('is_valid = ?')
        params.append(int(valid))
    where = ' WHERE ' + ' AND '.join(filters) if filters else ''
    query = f'FROM ({select}){where}'
    total = cur.execute(f'SELECT COUNT(*) {query}', params).fetchone()[0]
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    rows = cur.execute(
        f'SELECT * {query} ORDER BY "{sort}" {direction}, id {direction} LIMIT ? OFFSET ?',
        [*params, page_size, (page - 1) * page_size],
    ).fetchall()
    return dict(items=[dict(row) for row in rows], total=total, page=page,
                page_size=page_size, pages=pages)
