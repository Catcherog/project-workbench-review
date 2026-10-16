// A renewable user session is not an identity change. The callback may only
// perform an already-authorized read through the CLI, then return fresh status.
export function ensureLarkUserReady(auth, expectedOpenId, refreshViaRead) {
  const matches = value => value?.brand === 'feishu' &&
    value.identities?.user?.openId === expectedOpenId && !!expectedOpenId;
  if (!matches(auth)) throw Error('identity_mismatch');
  if (auth.identities.user.status === 'ready') return auth;
  if (auth.identities.user.status !== 'needs_refresh' || auth.identities.user.available !== true)
    throw Error('user_auth_not_ready');
  const refreshed = refreshViaRead();
  if (!matches(refreshed)) throw Error('identity_mismatch');
  if (refreshed.identities.user.status !== 'ready') throw Error('user_auth_not_ready');
  return refreshed;
}
