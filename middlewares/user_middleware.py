from aiogram import BaseMiddleware

from database import save_user


class UserMiddleware(
    BaseMiddleware
):

    async def __call__(
        self,
        handler,
        event,
        data
    ):

        user = getattr(
            event,
            "from_user",
            None
        )

        if user:

            await save_user(
                user.id,
                user.username,
                user.first_name,
                user.last_name
            )

        return await handler(
            event,
            data
        )