export const VIEWER_API = 'closure-viewer/0.1';

export async function requestJSON(path, body, token = '', transport = fetch) {
  const headers = {'X-Closure-API': VIEWER_API};
  const options = {headers};
  if (body !== undefined) {
    Object.assign(headers, {'Content-Type': 'application/json', 'X-Closure-Token': token});
    Object.assign(options, {method: 'POST', body: JSON.stringify(body)});
  }
  const response = await transport(path, options);
  if (response.headers.get('X-Closure-API') !== VIEWER_API) {
    throw Error('Viewer and backend versions differ. Restart Closure and reload this page.');
  }
  const result = await response.json();
  if (!response.ok) throw Error(typeof result.error === 'string' ? result.error : result.error?.message || 'Operation failed');
  return result;
}
